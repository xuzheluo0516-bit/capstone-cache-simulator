"""Single-source aggregation of per-request cache events.

The metrics layer consumes each RequestResult exactly once. Serializers receive
immutable snapshots and never mutate counters or re-count events.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping

from .engine import RequestResult
from .models import Resource, ResourceKey


@dataclass(frozen=True, slots=True)
class ClientMetrics:
    client_id: str
    requests: int
    hits: int
    misses: int
    request_hit_rate: float | None
    average_response_ms: float | None


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    step: int
    cumulative_origin_bytes: int
    cumulative_hits: int


@dataclass(frozen=True, slots=True)
class MetricsSummary:
    requests: int
    hits: int
    misses: int
    request_bytes: int
    hit_bytes: int
    origin_bytes: int
    total_response_ms: float
    request_hit_rate: float | None
    byte_hit_rate: float | None
    average_response_ms: float | None
    per_client: tuple[ClientMetrics, ...]


class MetricsAccumulator:
    """Consume engine events once and expose global/per-client metrics."""

    def __init__(
        self,
        resources: Mapping[ResourceKey, Resource],
        *,
        capacity_bytes: int | None = None,
    ) -> None:
        if capacity_bytes is not None and (
            not isinstance(capacity_bytes, int)
            or isinstance(capacity_bytes, bool)
            or capacity_bytes < 0
        ):
            raise ValueError("capacity_bytes must be a non-negative integer or None")
        self._resources = dict(resources)
        self._capacity_bytes = capacity_bytes
        self._seen_steps: set[int] = set()
        self._requests = 0
        self._hits = 0
        self._misses = 0
        self._request_bytes = 0
        self._hit_bytes = 0
        self._origin_bytes = 0
        self._total_response_ms = 0.0
        self._clients: dict[str, dict[str, float | int]] = {}

    def consume(self, event: RequestResult) -> MetricsSnapshot:
        """Add one event; duplicate request steps are rejected."""
        if event.step in self._seen_steps:
            raise ValueError(f"request step {event.step} was already counted")
        if event.resource_key not in self._resources:
            raise ValueError(f"unknown resource in event: {event.resource_key!r}")
        if self._capacity_bytes is not None:
            if event.cache_used_bytes > self._capacity_bytes:
                raise ValueError(
                    f"cache usage {event.cache_used_bytes} exceeds capacity "
                    f"{self._capacity_bytes} at step {event.step}"
                )

        resource_size = self._resources[event.resource_key].size_bytes
        if event.hit and event.origin_bytes != 0:
            raise ValueError(f"hit at step {event.step} cannot add origin traffic")
        if not event.hit and event.origin_bytes != resource_size:
            raise ValueError(
                f"miss at step {event.step} must add {resource_size} origin bytes, "
                f"got {event.origin_bytes}"
            )

        self._seen_steps.add(event.step)
        self._requests += 1
        self._request_bytes += resource_size
        self._total_response_ms += event.response_ms
        if event.hit:
            self._hits += 1
            self._hit_bytes += resource_size
        else:
            self._misses += 1
            self._origin_bytes += event.origin_bytes

        client = self._clients.setdefault(
            event.client_id,
            {"requests": 0, "hits": 0, "misses": 0, "response_ms": 0.0},
        )
        client["requests"] += 1
        client["response_ms"] += event.response_ms
        if event.hit:
            client["hits"] += 1
        else:
            client["misses"] += 1

        return MetricsSnapshot(
            step=event.step,
            cumulative_origin_bytes=self._origin_bytes,
            cumulative_hits=self._hits,
        )

    def consume_all(self, events: Iterable[RequestResult]) -> tuple[MetricsSnapshot, ...]:
        """Consume an event stream exactly once and return row snapshots."""
        return tuple(self.consume(event) for event in events)

    @property
    def summary(self) -> MetricsSummary:
        """Return a point-in-time immutable summary; undefined ratios are None."""
        clients = []
        for client_id, values in self._clients.items():
            count = int(values["requests"])
            hits = int(values["hits"])
            clients.append(
                ClientMetrics(
                    client_id=client_id,
                    requests=count,
                    hits=hits,
                    misses=int(values["misses"]),
                    request_hit_rate=hits / count if count else None,
                    average_response_ms=(
                        float(values["response_ms"]) / count if count else None
                    ),
                )
            )

        return MetricsSummary(
            requests=self._requests,
            hits=self._hits,
            misses=self._misses,
            request_bytes=self._request_bytes,
            hit_bytes=self._hit_bytes,
            origin_bytes=self._origin_bytes,
            total_response_ms=self._total_response_ms,
            request_hit_rate=(
                self._hits / self._requests if self._requests else None
            ),
            byte_hit_rate=(
                self._hit_bytes / self._request_bytes
                if self._request_bytes
                else None
            ),
            average_response_ms=(
                self._total_response_ms / self._requests
                if self._requests
                else None
            ),
            per_client=tuple(clients),
        )

    def reset(self) -> None:
        """Clear all counters so the same accumulator can serve a fresh run."""
        self._seen_steps.clear()
        self._requests = self._hits = self._misses = 0
        self._request_bytes = self._hit_bytes = self._origin_bytes = 0
        self._total_response_ms = 0.0
        self._clients.clear()
