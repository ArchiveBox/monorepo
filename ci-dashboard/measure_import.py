#!/usr/bin/env python3
"""Emit one machine-readable cold-import timing line for the CI collector."""

from __future__ import annotations

import importlib
import importlib.metadata
import json
import sys
import time


def measure(import_name: str) -> dict[str, object]:
    started = time.perf_counter_ns()
    package = importlib.import_module(import_name)
    elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
    version = getattr(package, "__version__", None) or getattr(package, "VERSION", None)
    if not version:
        try:
            version = importlib.metadata.version(import_name.replace("_", "-"))
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
    return {
        "metric": "python_import",
        "package": import_name,
        "version": str(version),
        "ttfi_ms": round(elapsed_ms, 3),
    }


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: measure_import.py IMPORT_NAME", file=sys.stderr)
        return 2
    result = measure(args[0])
    print(f"ABX_EVALS {json.dumps(result, separators=(',', ':'))}")
    print(f"{result['package']}.__version__={result['version']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
