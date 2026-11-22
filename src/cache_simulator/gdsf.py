"""GDSF: GreedyDual-Size-Frequency baseline (original form, no recency decay).

Every resident resource ``i`` carries a key

    K_i = L + F_i * dT_i / s_i

where

* ``L`` is a global "inflation" value that starts at 0. Whenever a resource is
  evicted, ``L`` is set to that resource's ``K``. Because ``L`` only grows,
  resources that were inserted or hit recently (computed with a larger ``L``)
  outrank old ones: this is GDSF's built-in form of recency.
* ``F_i`` is the cumulative access count since insertion (1 on insert, +1 on
  every hit, forgotten on eviction -- the same counting rule as the course LFU).
* ``dT_i = max(origin_latency_i - hit_latency, 0)`` is the time one hit saves.
* ``s_i`` is the size in bytes.

``K_i`` is recomputed (with the current ``L``) only when ``i`` is inserted or
hit. The resident with the smallest ``K`` is evicted; ties go to the least
recently accessed resource, then to the smallest ``ResourceKey``.

This is the baseline that RW-CSF is compared against: it has the same
value-density idea but replaces the global ``L`` by an explicit exponential
decay with half-life ``H``. The policy never rejects admission.

Engine interface note: size and latency are learned from
``should_admit(resource, ...)`` (called on every miss that fits, before
``on_insert``), or from the optional ``resources=`` constructor argument.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from numbers import Real

from .models import Resource, ResourceKey

DEFAULT_HIT_LATENCY_MS = 5.0


class GDSFPolicy:
    """Evict the resident with the smallest GreedyDual-Size-Frequency key."""

    def __init__(
        self,
        resources: Mapping[ResourceKey, Resource] | None = None,
        *,
        hit_latency_ms: float = DEFAULT_HIT_LATENCY_MS,
    ) -> None:
        if (
            not isinstance(hit_latency_ms, Real)
            or isinstance(hit_latency_ms, bool)
            or not math.isfinite(float(hit_latency_ms))
            or hit_latency_ms < 0
        ):
            raise ValueError("hit_latency_ms must be a finite non-negative number")
        self._resources = dict(resources) if resources is not None else None
        self._hit_latency_ms = float(hit_latency_ms)

        self._inflation = 0.0  # L
        self._count: dict[ResourceKey, int] = {}  # F since insertion
        self._last: dict[ResourceKey, int] = {}  # step of last access
        self._key_value: dict[ResourceKey, float] = {}  # K
        self._info: dict[ResourceKey, tuple[float, int]] = {}  # (dT, size)

    # ------------------------------------------------------------------ hooks

    def should_admit(self, resource: Resource, *, step: int) -> bool:
        """Record the resource's size and latency; always admit."""
        del step
        self._info[resource.key] = (
            max(resource.origin_latency_ms - self._hit_latency_ms, 0.0),
            resource.size_bytes,
        )
        return True

    def on_insert(self, key: ResourceKey, *, step: int) -> None:
        if key in self._count:
            raise ValueError(f"resource {key} is already tracked by the policy")
        self._count[key] = 1
        self._last[key] = step
        self._key_value[key] = self._compute_key(key)

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        if key not in self._count:
            raise ValueError(f"resource {key} is not tracked by the policy")
        self._count[key] += 1
        self._last[key] = step
        self._key_value[key] = self._compute_key(key)

    def select_victim(
        self,
        resident_keys: Sequence[ResourceKey],
        *,
        step: int,
    ) -> ResourceKey:
        del step
        if not resident_keys:
            raise ValueError("cannot select a victim from an empty cache")
        missing = [key for key in resident_keys if key not in self._count]
        if missing:
            raise ValueError(f"policy has no record for resident key {missing[0]}")
        return min(
            resident_keys,
            key=lambda key: (self._key_value[key], self._last[key], key),
        )

    def on_evict(self, key: ResourceKey, *, step: int) -> None:
        del step
        if key not in self._count:
            raise ValueError(f"resource {key} is not tracked by the policy")
        value = self._key_value[key]
        if math.isfinite(value):  # a zero-byte resource (K = inf) must not poison L
            self._inflation = value
        del self._count[key]
        del self._last[key]
        del self._key_value[key]

    def reset(self) -> None:
        self._inflation = 0.0
        self._count.clear()
        self._last.clear()
        self._key_value.clear()
        self._info.clear()

    # --------------------------------------------------------------- analysis

    @property
    def inflation(self) -> float:
        """Current value of the global inflation term L."""
        return self._inflation

    def key_value(self, key: ResourceKey) -> float:
        """Return the stored K of a resident key."""
        if key not in self._key_value:
            raise ValueError(f"resource {key} is not tracked by the policy")
        return self._key_value[key]

    # ---------------------------------------------------------------- helpers

    def _compute_key(self, key: ResourceKey) -> float:
        gain_ms, size = self._lookup(key)
        if size == 0:
            return math.inf
        return self._inflation + self._count[key] * gain_ms / size

    def _lookup(self, key: ResourceKey) -> tuple[float, int]:
        info = self._info.get(key)
        if info is None and self._resources is not None and key in self._resources:
            resource = self._resources[key]
            info = (
                max(resource.origin_latency_ms - self._hit_latency_ms, 0.0),
                resource.size_bytes,
            )
            self._info[key] = info
        if info is None:
            raise ValueError(
                f"no size/latency known for {key}; the engine calls should_admit "
                "first, or pass resources= to the constructor"
            )
        return info
