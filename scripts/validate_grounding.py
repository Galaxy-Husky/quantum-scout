#!/usr/bin/env python3
"""Run the same grounding gate locally; always write failures before returning 2."""
import argparse
import importlib.util
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def grounding_gate():
    path = Path(__file__).resolve().parents[1] / "assets/quantum_grounding/executor.py"
    spec = importlib.util.spec_from_file_location("quantum_grounding", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request_json", type=Path)
    parser.add_argument("report_json", type=Path)
    args = parser.parse_args()
    result = grounding_gate().validate(json.loads(args.request_json.read_text(encoding="utf-8")))
    args.report_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 2 if result["grounding_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
