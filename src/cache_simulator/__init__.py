"""Core types, input parsing, and simulation engine for the shared cache."""

from .engine import (
    DEFAULT_CAPACITY_BYTES,
    DEFAULT_HIT_LATENCY_MS,
    EvictionPolicy,
    RequestResult,
    SharedCacheEngine,
)
from .input_parser import InputValidationError, SimulationInputs, load_inputs
from .models import Request, Resource, ResourceKey

__all__ = [
    "DEFAULT_CAPACITY_BYTES",
    "DEFAULT_HIT_LATENCY_MS",
    "EvictionPolicy",
    "InputValidationError",
    "Request",
    "RequestResult",
    "Resource",
    "ResourceKey",
    "SharedCacheEngine",
    "SimulationInputs",
    "load_inputs",
]
