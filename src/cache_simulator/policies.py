"""Standard FIFO and LRU replacement policies for the shared cache engine."""

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
