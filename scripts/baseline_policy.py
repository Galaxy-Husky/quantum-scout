"""Execution compatibility is separate from document provenance; no historical migration."""
import hashlib
import json
from pathlib import Path
import warnings


def _baseline(root, directories, names=()):
    files = {}
    paths = [p for directory in directories for p in sorted((root / directory).rglob('*'))]
    paths += [root / name for name in names]
    for path in paths:
        if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
            files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    sha = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'sha256': sha, 'files': files}


def skill_baseline(root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    return {'version': 3, 'execution_baseline': _baseline(root, ('scripts', 'config', 'assets')),
            'document_baseline': _baseline(root, ('references',), ('SKILL.md', 'CHANGELOG.md'))}


def execution_baseline(meta, current):
    online = meta.get('online', {})
    previous = online.get('skill_baseline')
    if previous is None:
        if online.get('invocations'):
            raise ValueError('Historical workspace has no execution baseline; use its archived skill or a new workspace')
        return current
    if (previous.get('version') != 3 or current.get('version') != 3
            or previous.get('execution_baseline') != current.get('execution_baseline')):
        raise ValueError('Skill baseline changed; use the pinned skill or a new workspace')
    if previous.get('document_baseline') != current.get('document_baseline'):
        warnings.warn('Skill document baseline changed; execution baseline unchanged', UserWarning)
    return previous
