"""Policy-independent shared cache simulation engine."""

from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass
from numbers import Real
from typing import Collection, Mapping, Protocol, Sequence

from .models import Request, Resource, ResourceKey

DEFAULT_CAPACITY_BYTES = 100 * 1024
DEFAULT_HIT_LATENCY_MS = 5.0


class EvictionPolicy(Protocol):
    """Stateful replacement policy interface consumed by the cache engine.

    The engine owns residency, byte accounting, admission, and repeated
    eviction. A policy owns only the state needed to choose a victim.
    """

    def on_hit(self, key: ResourceKey, *, step: int) -> None:
        """Observe a hit before the request result is emitted."""

    def on_insert(self, key: ResourceKey, *, step: int) -> None:
        """Observe a committed insertion."""

    def select_victim(
        self,
        resident_keys: Sequence[ResourceKey],
        *,
        step: int,
    ) -> ResourceKey:
        """Return one key from ``resident_keys`` to evict next."""

    def on_evict(self, key: ResourceKey, *, step: int) -> None:
        """Observe a committed eviction."""

    def reset(self) -> None:
        """Discard all policy state for a new simulation run."""


class PolicyContractError(RuntimeError):
    """Raised when a replacement policy violates the engine contract."""


@dataclass(frozen=True, slots=True)
class RequestResult:
    """One event for the metrics layer to consume exactly once."""

    request: Request
    hit: bool
    evicted: tuple[ResourceKey, ...]
    cache_contents_oldest_first: tuple[ResourceKey, ...]
    cache_used_bytes: int
    response_ms: float
    origin_bytes: int

    @property
    def step(self) -> int:
        return self.request.sequence

    @property
    def resource_key(self) -> ResourceKey:
        return self.request.key

    @property
    def client_id(self) -> str:
        return self.request.client_id

    @property
    def result(self) -> str:
        return "HIT" if self.hit else "MISS"


class SharedCacheEngine:
    """A shared, byte-capacity-limited cache with a pluggable policy."""

    def __init__(
        self,
        resources: Mapping[ResourceKey, Resource],
        policy: EvictionPolicy,
        *,
        capacity_bytes: int = DEFAULT_CAPACITY_BYTES,
        hit_latency_ms: float = DEFAULT_HIT_LATENCY_MS,
    ) -> None:
        if (
            not isinstance(capacity_bytes, int)
            or isinstance(capacity_bytes, bool)
            or capacity_bytes < 0
        ):
            raise ValueError("capacity_bytes must be a non-negative integer")
        if (
            not isinstance(hit_latency_ms, Real)
            or isinstance(hit_latency_ms, bool)
            or not math.isfinite(float(hit_latency_ms))
            or hit_latency_ms < 0
        ):
            raise ValueError("hit_latency_ms must be a finite non-negative number")

        self._resources = dict(resources)
        for mapping_key, resource in self._resources.items():
            if mapping_key != resource.key:
                raise ValueError("resources mapping key does not match resource.key")
            if (
                not isinstance(resource.size_bytes, int)
                or isinstance(resource.size_bytes, bool)
                or resource.size_bytes < 0
            ):
                raise ValueError("resource.size_bytes must be a non-negative integer")
            if (
                not isinstance(resource.origin_latency_ms, Real)
                or isinstance(resource.origin_latency_ms, bool)
                or not math.isfinite(float(resource.origin_latency_ms))
                or resource.origin_latency_ms < 0
            ):
                raise ValueError(
                    "resource.origin_latency_ms must be a finite "
                    "non-negative number"
                )
        self._policy = policy
        self._capacity_bytes = capacity_bytes
        self._hit_latency_ms = float(hit_latency_ms)
        self._cache: OrderedDict[ResourceKey, Resource] = OrderedDict()
        self._used_bytes = 0
        self._processed_steps: set[int] = set()
        self._policy.reset()

    @property
    def capacity_bytes(self) -> int:
        return self._capacity_bytes

    @property
    def hit_latency_ms(self) -> float:
        return self._hit_latency_ms

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    @property
    def cache_contents_oldest_first(self) -> tuple[ResourceKey, ...]:
        return tuple(self._cache)

    def process(self, request: Request) -> RequestResult:
        """Process one request and return its unique result event."""

        self._validate_request(request)
        if request.sequence in self._processed_steps:
            raise ValueError(f"request step {request.sequence} was already processed")
        self._processed_steps.add(request.sequence)

        resource = self._resources[request.key]
        if request.key in self._cache:
            self._policy.on_hit(request.key, step=request.sequence)
            return self._result(
                request,
                hit=True,
                evicted=(),
                response_ms=self._hit_latency_ms,
                origin_bytes=0,
            )

        evicted: list[ResourceKey] = []
        if resource.size_bytes <= self._capacity_bytes:
            while self._used_bytes + resource.size_bytes > self._capacity_bytes:
                victim = self._policy.select_victim(
                    tuple(self._cache),
                    step=request.sequence,
                )
                if victim not in self._cache:
                    raise PolicyContractError(
                        f"policy selected non-resident key {victim!r} at step "
                        f"{request.sequence}"
                    )
                removed = self._cache.pop(victim)
                self._used_bytes -= removed.size_bytes
                evicted.append(victim)
                self._policy.on_evict(victim, step=request.sequence)

            self._cache[request.key] = resource
            self._used_bytes += resource.size_bytes
            self._policy.on_insert(request.key, step=request.sequence)

        return self._result(
            request,
            hit=False,
            evicted=tuple(evicted),
            response_ms=resource.origin_latency_ms,
            origin_bytes=resource.size_bytes,
        )

    def process_all(self, requests: Collection[Request]) -> tuple[RequestResult, ...]:
        """Process a complete request trace in its supplied order."""

        return tuple(self.process(request) for request in requests)

    def reset(self) -> None:
        """Restore empty-cache state for an independent simulation run."""

        self._cache.clear()
        self._used_bytes = 0
        self._processed_steps.clear()
        self._policy.reset()

    def _validate_request(self, request: Request) -> None:
        if not isinstance(request.sequence, int) or request.sequence < 1:
            raise ValueError("request.sequence must be a positive integer")
        if request.method != "GET":
            raise ValueError("only GET requests can be simulated")
        if request.key not in self._resources:
            raise ValueError(f"request references unknown resource {request.key!r}")

    def _result(
        self,
        request: Request,
        *,
        hit: bool,
        evicted: tuple[ResourceKey, ...],
        response_ms: float,
        origin_bytes: int,
    ) -> RequestResult:
        return RequestResult(
            request=request,
            hit=hit,
            evicted=evicted,
            cache_contents_oldest_first=self.cache_contents_oldest_first,
            cache_used_bytes=self._used_bytes,
            response_ms=response_ms,
            origin_bytes=origin_bytes,
        )
