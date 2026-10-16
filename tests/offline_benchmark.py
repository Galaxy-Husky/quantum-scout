#!/usr/bin/env python3
"""Reproducible synthetic parser/projection/export benchmark; no real model latency."""
import argparse
from copy import deepcopy
import hashlib
import json
import platform
import resource
import statistics
import sys
from pathlib import Path
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import searchos_adapter as adapter
from export_batch import build
from render_calibration import render
from searchos_online import DEFAULTS
from searchos_network import source_segments
from test_network_boundaries import pdf_document


def benchmark(samples=3):
    if type(samples) is not int or samples < 1:
        raise ValueError('samples must be a positive integer')
    pdf = pdf_document(['BT /F1 12 Tf 40 700 Td (Generated benchmark evidence page %d.) Tj ET' % i
                        for i in range(24)])
    rows = []
    def measure(name, fn):
        durations = []
        for _ in range(samples):
            start = time.perf_counter()
            fn()
            durations.append(time.perf_counter() - start)
        rows.append({'operation': name, 'seconds': durations, 'median_seconds': statistics.median(durations),
                     'max_seconds': max(durations)})
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'benchmark'
        cases = [f'TEST-{i:04}' for i in range(1, 6)]
        adapter.prepare(path, case_ids=cases)
        meta = adapter.load(path)
        config = {**DEFAULTS, 'providers': ['serper'], 'cases': {cid: {'description': 'Synthetic benchmark'} for cid in cases}}
        sources = {}
        segments = source_segments(pdf, 'application/pdf')
        assert len(segments) == 24
        for i in range(12):
            url = f'https://fixture.example/benchmark-{i}'
            source = {'source_id': f'benchmark-{i}', 'run_id': path.name, 'status': 'opened', 'url': url,
                'document_version': 'synthetic-24-pages', 'segments': segments,
                'text': '\n\n'.join(f"[{s['location']}]\n{s['text']}" for s in segments)}
            sources[adapter.digest(url)] = {'url': url, 'status': 'opened', 'at': adapter.now(), 'source': source}
        meta['online'] = {'sources': sources, 'events': [], 'searches': {}, 'assessments': {}, 'config': config,
            'invocations': [{'status': 'incomplete', 'stop_reason': 'budget_exhausted',
                              'stop_evidence': {'budget_cause': 'model_call_limit'}}]}
        measure('parse_24_page_generated_pdf', lambda: source_segments(pdf, 'application/pdf'))
        measure('project_5_cases_12_sources_no_reviewed_candidates', lambda: adapter.project(deepcopy(meta)))
        measure('export_and_render_5_cases_12_sources_no_reviewed_candidates', lambda: render(build(deepcopy(meta))))
    return {'scope': 'Synthetic offline baseline; no LLM, network, dense evidence graph or capacity guarantee',
            'environment': {'python': platform.python_version(), 'platform': platform.platform()},
            'samples': samples, 'fixture': {'pdf_pages': 24, 'pdf_sha256': hashlib.sha256(pdf).hexdigest(),
                'cases': 5, 'opened_sources': 12, 'reviewed_candidates': 0}, 'operations': rows,
            'memory': {'parent_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       'child_peak_rss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss,
                       'scope': 'Process lifetime high-water RSS on Linux; not a per-stage delta'},
            'real_model_latency_seconds': None,
            'warning_policy': 'Investigate >2x median against a same-environment baseline; advisory only',
            'hard_limits': {'download_bytes_default': 20000000, 'pdf_parser_timeout_seconds': 30,
                            'source': 'searchos_network.py defaults; not measured capacity'}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(args.samples)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
