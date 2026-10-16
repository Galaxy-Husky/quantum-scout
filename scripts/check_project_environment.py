#!/usr/bin/env python3
"""Check the current extraction/retrieval stack without live service calls."""
import argparse
import importlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import sys

from searchos_project import ProjectLayout, save


def check():
    import contextgem_extractor  # disables LiteLLM remote model metadata loading
    modules = {'searchos': 'searchos', 'contextgem': 'contextgem', 'httpx': 'httpx',
               'lxml': 'lxml', 'pydantic': 'pydantic', 'PyYAML': 'yaml',
               'python-dotenv': 'dotenv', 'tavily-python': 'tavily'}
    libraries = {}
    for package, module in modules.items():
        try:
            importlib.import_module(module)
            libraries[package] = {'version': importlib.metadata.version(package), 'import': 'passed'}
        except Exception as exc:
            libraries[package] = {'import': 'failed', 'error_type': type(exc).__name__}
    return {'python': sys.version.split()[0], 'executable': sys.executable,
        'libraries': libraries, 'libraries_ready': all(r['import'] == 'passed' for r in libraries.values()),
        'pdftotext': shutil.which('pdftotext'), 'model_inference_tested': False,
        'asreview': 'heuristic_inspiration_only', 'deepdive': 'ledger_design_only'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    report = check()
    save(ProjectLayout(args.project_root).environment, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['libraries_ready'] and report['pdftotext'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
