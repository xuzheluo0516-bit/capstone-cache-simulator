"""RW-CSF: Recency-Weighted Cost-Size-Frequency replacement policy.

Every resident resource ``i`` is scored with

    P_i(n) = F_i(n) * dT_i / s_i

where

* ``F_i(n)`` is the recency-weighted access count. Each access is worth one
  point and loses half of its weight every ``half_life`` requests::

      F_i(n) = sum over accesses j of 2 ** (-(n - n_j) / half_life)

  It is maintained incrementally: on a hit, ``F <- F * 2**(-(n - last)/H) + 1``.
* ``dT_i = max(origin_latency_i - hit_latency, 0)`` is the time one hit saves.
* ``s_i`` is the resource size in bytes.

The resident with the smallest ``P`` is evicted. Ties go to the least recently
accessed resource, then to the smallest ``ResourceKey`` (a deterministic
fallback). The policy never rejects admission.

Special cases that make the policy easy to sanity-check:

* ``use_latency=False, use_size=False, half_life=math.inf`` behaves like LFU.
* ``use_latency=False, use_size=False, half_life=1`` behaves like LRU.

Engine interface note: the engine only passes keys and steps to most
callbacks. Size and latency are learned from ``should_admit(resource, ...)``,
which the engine calls on every miss that fits, before ``on_insert``. It always
returns ``True``. Alternatively pass ``resources=`` to the constructor.
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from numbers import Real

from .models import Resource, ResourceKey

DEFAULT_HALF_LIFE = 20.0  # requests; placeholder, to be chosen by the H experiment
DEFAULT_HIT_LATENCY_MS = 5.0
DEFAULT_FORGET_LIMIT = 1000


class RWCSFPolicy:
    """Evict the resident with the lowest recency-weighted value density."""

    def __init__(
        self,
        resources: Mapping[ResourceKey, Resource] | None = None,
        *,
        half_life: float = DEFAULT_HALF_LIFE,
        hit_latency_ms: float = DEFAULT_HIT_LATENCY_MS,
        use_latency: bool = True,
        use_size: bool = True,
        inherit: bool = False,
        forget_limit: int = DEFAULT_FORGET_LIMIT,
    ) -> None:
        if (
            not isinstance(half_life, Real)
            or isinstance(half_life, bool)
            or not half_life > 0  # also rejects NaN; math.inf is allowed
        ):
            raise ValueError("half_life must be a positive number (inf allowed)")
        if (
            not isinstance(hit_latency_ms, Real)
            or isinstance(hit_latency_ms, bool)
            or not math.isfinite(float(hit_latency_ms))
            or hit_latency_ms < 0
        ):
            raise ValueError("hit_latency_ms must be a finite non-negative number")
        if (
            not isinstance(forget_limit, int)
            or isinstance(forget_limit, bool)
            or forget_limit < 0
        ):
            raise ValueError("forget_limit must be a non-negative integer")

        self._resources = dict(resources) if resources is not None else None
        self._half_life = float(half_life)
        self._hit_latency_ms = float(hit_latency_ms)
        self._use_latency = bool(use_latency)
        self._use_size = bool(use_size)
        self._inherit = bool(inherit)
        self._forget_limit = forget_limit

        self._freq: dict[ResourceKey, float] = {}  # F as of the last access
        self._last: dict[ResourceKey, int] = {}  # step of the last access
        self._info: dict[ResourceKey, tuple[float, int]] = {}  # (dT, size)
        self._forgotten: OrderedDict[ResourceKey, tuple[float, int]] = OrderedDict()

    # ------------------------------------------------------------------ hooks

    def should_admit(self, resource: Resource, *, step: int) -> bool:
        """Record the resource's size and latency; always admit."""
        del step
        self._info[resource.key] = self._derive(resource)
        return True

    def on_insert(self, key: ResourceKey, *, step: int) -> None:
        if key in self._freq:
            raise ValueError(f"resource {key} is already tracked by the policy")
        freq = 1.0
        if self._inherit:
            old = self._forgotten.pop(key, None)
            if old is not None:
                old_freq, old_last = old
                freq += old_freq * self._decay(old_last, step)
        self._freq[key] = freq
        self._last[key] = step

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        if key not in self._freq:
            raise ValueError(f"resource {key} is not tracked by the policy")
        self._freq[key] = self._freq[key] * self._decay(self._last[key], step) + 1.0
        self._last[key] = step

    def select_victim(
        self,
        resident_keys: Sequence[ResourceKey],
        *,
        step: int,
    ) -> ResourceKey:
        if not resident_keys:
            raise ValueError("cannot select a victim from an empty cache")
        missing = [key for key in resident_keys if key not in self._freq]
        if missing:
            raise ValueError(f"policy has no record for resident key {missing[0]}")
        return min(
            resident_keys,
            key=lambda key: (self.priority(key, step=step), self._last[key], key),
        )

    def on_evict(self, key: ResourceKey, *, step: int) -> None:
        del step
        if key not in self._freq:
            raise ValueError(f"resource {key} is not tracked by the policy")
        if self._inherit and self._forget_limit > 0:
            self._forgotten.pop(key, None)
            self._forgotten[key] = (self._freq[key], self._last[key])
            while len(self._forgotten) > self._forget_limit:
                self._forgotten.popitem(last=False)  # drop the oldest memory
        del self._freq[key]
        del self._last[key]

    def reset(self) -> None:
        self._freq.clear()
        self._last.clear()
        self._info.clear()
        self._forgotten.clear()

    # --------------------------------------------------------------- analysis

    def priority(self, key: ResourceKey, *, step: int) -> float:
        """Return P = F * dT / s for a resident key at request ``step``."""
        if key not in self._freq:
            raise ValueError(f"resource {key} is not tracked by the policy")
        gain_ms, size = self._lookup(key)
        if size == 0:
            return math.inf  # evicting a zero-byte resource frees no space
        freq_now = self._freq[key] * self._decay(self._last[key], step)
        return freq_now * gain_ms / size

    # ---------------------------------------------------------------- helpers

    def _decay(self, from_step: int, to_step: int) -> float:
        # half_life == inf gives exponent -0.0, so the factor is exactly 1.
        return 2.0 ** (-(to_step - from_step) / self._half_life)

    def _derive(self, resource: Resource) -> tuple[float, int]:
        gain_ms = (
            max(resource.origin_latency_ms - self._hit_latency_ms, 0.0)
            if self._use_latency
            else 1.0
        )
        size = resource.size_bytes if self._use_size else 1
        return gain_ms, size

    def _lookup(self, key: ResourceKey) -> tuple[float, int]:
        info = self._info.get(key)
        if info is None and self._resources is not None and key in self._resources:
            info = self._derive(self._resources[key])
            self._info[key] = info
        if info is None:
            raise ValueError(
                f"no size/latency known for {key}; the engine calls should_admit "
                "first, or pass resources= to the constructor"
            )
        return info
