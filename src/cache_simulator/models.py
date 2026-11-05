"""Immutable objects shared by the parser, cache engine, and metrics code."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, order=True, slots=True)
class ResourceKey:
    """The cache identity for a resource."""

    scheme: str
    host: str
    path: str

    def __str__(self) -> str:
        return f"{self.scheme}://{self.host}{self.path}"


@dataclass(frozen=True, slots=True)
class Resource:
    """Metadata needed by the simulator for one cacheable object."""

    key: ResourceKey
    status_code: int
    content_type: str
    size_bytes: int
    origin_latency_ms: float
    cache_control: str


@dataclass(frozen=True, slots=True)
class Request:
    """A request with a stable one-based sequence assigned after sorting."""

    timestamp: datetime
    client_id: str
    method: str
    key: ResourceKey
    sequence: int
    source_line: int = field(compare=False)
