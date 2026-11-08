"""Module entry point so ``python -m cache_simulator`` runs the CLI."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
