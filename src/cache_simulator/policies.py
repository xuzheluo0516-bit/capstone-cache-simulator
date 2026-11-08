"""Standard FIFO, LRU, and LFU replacement policies for the shared cache engine."""

from __future__ import annotations

from collections.abc import Sequence

from .models import ResourceKey


class _OrderedPolicy:
    """Base for policies that rank resident resources by a stable request step."""

    def __init__(self) -> None:
        self._order: dict[ResourceKey, int] = {}

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        """Observe a hit. FIFO intentionally leaves its order unchanged."""

    def on_insert(self, key: ResourceKey, *, step: int) -> None:
        if key in self._order:
            raise ValueError(f"resource {key} is already tracked by the policy")
        self._order[key] = step

    def select_victim(
        self,
        resident_keys: Sequence[ResourceKey],
        *,
        step: int,
    ) -> ResourceKey:
        del step
        if not resident_keys:
            raise ValueError("cannot select a victim from an empty cache")
        missing = [key for key in resident_keys if key not in self._order]
        if missing:
            raise ValueError(f"policy has no ordering record for resident key {missing[0]}")
        # The stable request sequence is unique in a parsed trace. ResourceKey
        # provides a deterministic secondary key for direct/manual engine use.
        return min(resident_keys, key=lambda key: (self._order[key], key))

    def on_evict(self, key: ResourceKey, *, step: int) -> None:
        del step
        if key not in self._order:
            raise ValueError(f"resource {key} is not tracked by the policy")
        del self._order[key]

    def reset(self) -> None:
        self._order.clear()


class FIFOPolicy(_OrderedPolicy):
    """Evict the resource that entered the cache earliest.

    A hit never changes insertion order.
    """


class LRUPolicy(_OrderedPolicy):
    """Evict the resource whose most recent access is oldest."""

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        if key not in self._order:
            raise ValueError(f"resource {key} is not tracked by the policy")
        self._order[key] = step


class LFUPolicy:
    """Evict the resource used least often since its insertion.

    Frequency starts at one on insertion and increases by one on every hit.
    Equal frequencies are broken by least recent access using the stable
    request sequence. Eviction removes the policy record, so a resource that is
    inserted again restarts at frequency one and does not inherit its prior
    frequency or access history.
    """

    def __init__(self) -> None:
        self._frequencies: dict[ResourceKey, int] = {}
        self._last_access: dict[ResourceKey, int] = {}

    def on_insert(self, key: ResourceKey, *, step: int) -> None:
        if key in self._frequencies:
            raise ValueError(f"resource {key} is already tracked by the policy")
        self._frequencies[key] = 1
        self._last_access[key] = step

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        if key not in self._frequencies:
            raise ValueError(f"resource {key} is not tracked by the policy")
        self._frequencies[key] += 1
        self._last_access[key] = step

    def select_victim(
        self,
        resident_keys: Sequence[ResourceKey],
        *,
        step: int,
    ) -> ResourceKey:
        del step
        if not resident_keys:
            raise ValueError("cannot select a victim from an empty cache")
        missing = [key for key in resident_keys if key not in self._frequencies]
        if missing:
            raise ValueError(
                f"policy has no frequency record for resident key {missing[0]}"
            )
        # Frequency is the primary LFU ranking. The stable request sequence
        # breaks ties by least recent access, and ResourceKey is a deterministic
        # final fallback for direct/manual engine use.
        return min(
            resident_keys,
            key=lambda key: (
                self._frequencies[key],
                self._last_access[key],
                key,
            ),
        )

    def on_evict(self, key: ResourceKey, *, step: int) -> None:
        del step
        if key not in self._frequencies:
            raise ValueError(f"resource {key} is not tracked by the policy")
        del self._frequencies[key]
        del self._last_access[key]

    def reset(self) -> None:
        self._frequencies.clear()
        self._last_access.clear()
