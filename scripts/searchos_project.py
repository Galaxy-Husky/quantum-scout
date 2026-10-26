#!/usr/bin/env python3
"""Shared output layout and generators for a Quantum Scout SearchOS project."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import unquote, urlparse


class ProjectLayout:
    def __init__(self, root=None):
        self.root = Path(root or Path.cwd()).resolve()
        self.base = self.root / 'artifacts' / 'quantum-scout'
        self.cache = self.base / 'cache'
        self.temporary = self.base / 'tmp'
        self.runs = self.base / 'runs'
        self.config = self.root / 'searchos' / 'config' / 'online-pilot.json'
        self.env_template = self.root / 'searchos' / 'config' / 'env.example'
        self.schema = self.base / 'config' / 'schema.json'
        self.manifest = self.base / 'runtime' / 'manifest.json'
        self.lock = self.base / 'runtime' / 'requirements.lock'
        self.offline = self.base / 'validation' / 'offline.json'
        self.doctor = self.base / 'validation' / 'doctor.json'
        self.online = self.base / 'validation' / 'online.json'
        self.environment = self.base / 'validation' / 'environment.json'
        self.workspaces = self.base / 'workspaces'

    def new_workspace(self, prefix='online'):
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        return self.workspaces / f'{prefix}-{stamp}'

    def relative(self, path):
        return os.path.relpath(Path(path).resolve(), self.root)


class WorkspaceLayout:
    """One canonical layout for current workspaces."""
    def __init__(self, root):
        self.root = Path(root)
        self.state = self.root / 'state'
        self.adapter = self.state / 'quantum_adapter.json'
        self.schema = self.root / 'config/quantum_schema.json'
        self.socm = self.state / 'socm'
        self.report = self.root / 'reports/online.json'
        self.replay = self.root / 'inputs/replay.json'


def save(path, data):
    """Atomic generated output; create its intended parent, not a root fallback."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize(layout, case_id, description, queries):
    import re
    if not re.fullmatch(r'[A-Z]{3,4}-\d{4}', case_id) or not description.strip():
        raise ValueError('A valid case ID and nonempty description are required')
    config = {'cases': {case_id: {'description': description, 'queries': queries}}}
    template = Path(__file__).resolve().parents[1] / 'assets/searchos.env.example'
    written = []
    for path, text in ((layout.config, json.dumps(config, ensure_ascii=False, indent=2) + '\n'),
                       (layout.env_template, template.read_text())):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open('x') as stream:
                stream.write(text)
            written.append(layout.relative(path))
        except FileExistsError:
            pass  # Never replace an existing user's configuration.
    return {'created': written, 'config': layout.relative(layout.config)}


def installed_source(name):
    """Resolve a local install source from package metadata, never a machine-specific guess."""
    distribution = importlib.metadata.distribution(name)
    direct = json.loads(distribution.read_text('direct_url.json') or '{}')
    url = urlparse(direct.get('url', ''))
    return (Path(unquote(url.path)).resolve()
            if url.scheme == 'file' and url.netloc in {'', 'localhost'} else None)


def snapshot_runtime(layout, repository=None):
    repository = Path(repository).resolve() if repository is not None else installed_source('searchos')
    if repository is None:
        raise ValueError('SearchOS has no local source metadata; supply --searchos-repo')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repository), *args], text=True).strip()
    revision, branch = git('rev-parse', 'HEAD'), git('branch', '--show-current')
    packages = {d.metadata['Name']: d.version for d in importlib.metadata.distributions()
                if d.metadata.get('Name') and d.metadata['Name'].lower() not in {'searchos', 'contextgem', 'quantum-scout'}}
    lock = '# Environment snapshot, not an install lock; local source observations are in manifest.json\n'
    lock += ''.join(f'{name}=={packages[name]}\n' for name in sorted(packages, key=str.lower))
    manifest = json.loads(layout.manifest.read_text()) if layout.manifest.exists() else {}
    manifest.update(python=sys.executable, python_version=sys.version.split()[0],
        repository=str(repository), repository_revision=revision, branch=branch,
        repository_dirty=bool(git('status', '--porcelain')),
        workspace_root=str(layout.workspaces), dependencies_lock=layout.relative(layout.lock),
        lock_sha256=hashlib.sha256(lock.encode()).hexdigest(),
        online_entrypoint=str(Path(__file__).with_name('searchos_online.py').resolve()),
        source_revision_role='observed_checkout_not_installed_build_proof',
        captured_at=datetime.now(timezone.utc).isoformat())
    if (layout.root / 'uv.lock').exists():
        manifest.update(project_root=str(layout.root), install_mode='uv_project',
                        project_lock='uv.lock',
                        project_lock_sha256=hashlib.sha256((layout.root / 'uv.lock').read_bytes()).hexdigest())
    manifest.pop('halt_repository', None)
    manifest.pop('halt_verifier', None)
    manifest['integrations'] = {}
    for name in ('searchos', 'contextgem'):
        repo = installed_source(name)
        entry = {'version': importlib.metadata.version(name),
                 'role': 'runtime' if name == 'searchos' else 'extraction'}
        if repo is not None:
            entry['path'] = str(repo)
            result = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                                    capture_output=True, text=True)
            if result.returncode == 0:
                entry['revision'] = result.stdout.strip()
                status = subprocess.run(['git', '-C', str(repo), 'status', '--porcelain'],
                                        capture_output=True, text=True)
                entry['dirty'] = bool(status.stdout.strip()) if status.returncode == 0 else None
        manifest['integrations'][name] = entry
    save(layout.lock, lock)
    save(layout.manifest, manifest)
    return {'manifest': layout.relative(layout.manifest), 'lock': layout.relative(layout.lock)}


def save_online_validation(layout, workspace, result):
    meta = json.loads(WorkspaceLayout(workspace).adapter.read_text())
    online = meta['online']
    responses = [e for e in online['events'] if e['kind'] == 'model_response']
    usage = [e['usage'] for e in responses if e.get('usage')]
    from online_policy import attribution_metrics
    from cost_policy import model_costs
    report = {'workspace': layout.relative(workspace),
        'review_pipeline': 'attribution_then_semantic',
        'live_attribution_tested': bool(meta.get('attributions')),
        'attribution': attribution_metrics(meta),
        'cost_breakdown': model_costs(online['events']),
        'live_search_tested': any(r['status'] == 'succeeded' for r in online['searches'].values()),
        'live_source_open_tested': any(r['status'] == 'opened' for r in online['sources'].values()),
        'live_model_extraction_tested': any(e['role'] == 'extraction' for e in responses),
        'live_independent_review_tested': any(r['reviewer_id'] == 'online-judge' and 'domain_rule_met' in r for r in meta['reviews']),
        'model_calls_total': sum(i.get('model_calls', 0) for i in online['invocations']),
        'usage': {k: sum(u.get(k, 0) for u in usage) for k in ('input_tokens', 'output_tokens', 'total_tokens')},
        'verified_cells': result['coverage']['filled'], 'total_cells': result['coverage']['total_cells'],
        'last_stop_reason': result['stop_reason']}
    save(layout.online, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init')
    init.add_argument('--case-id', required=True)
    init.add_argument('--description', required=True)
    init.add_argument('--query', action='append', default=[])
    runtime = sub.add_parser('runtime')
    runtime.add_argument('--searchos-repo', type=Path,
                         help='Default: installed SearchOS local source metadata')
    args = parser.parse_args()
    layout = ProjectLayout(args.project_root)
    result = (initialize(layout, args.case_id, args.description, args.query) if args.command == 'init'
              else snapshot_runtime(layout, args.searchos_repo))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
