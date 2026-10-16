"""Validate accounting and baseline integrity rather than generated wording."""
import hashlib
from copy import deepcopy

import pytest

from coverage_inventory import inventory


@pytest.fixture
def measured(tmp_path):
    root = tmp_path / 'skill'
    (root / 'scripts').mkdir(parents=True)
    (root / 'assets').mkdir()
    source = 'def main():\n    return 1\n\nif __name__ == "__main__":\n    main()\n'
    (root / 'scripts/a.py').write_text(source)
    (root / 'assets/b.py').write_text('x = 1\n')
    counts = dict(covered_lines=1, num_statements=4, missing_lines=3,
                  covered_branches=1, num_branches=2, missing_branches=1)
    empty = dict.fromkeys(counts, 0)
    row = {'summary': counts, 'missing_lines': [1, 2, 5], 'missing_branches': [[4, -1]]}
    data = {'meta': {'branch_coverage': True}, 'totals': counts,
            'files': {str(root / 'scripts/a.py'): row,
                      str(root / 'assets/b.py'): {'summary': empty, 'missing_lines': [], 'missing_branches': []}}}
    manifest = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob('*.py')}
    return data, root, manifest


def test_totals_preserved_with_cli_as_subset_and_zero_denominators(measured):
    data, root, manifest = measured
    report = inventory(data, root, root, 'parent_only', manifest)
    assert report['totals']['missing_lines'] == 3
    assert sum(r['missing_lines'] for r in report['by_area'].values()) == 3
    assert report['by_area']['assets']['line_percent'] is None
    assert report['totals']['line_percent'] == 25
    assert report['totals']['branch_percent'] == 50
    assert report['missing_by_surface']['cli_entry']['missing_lines'] == 3
    assert sum(r['missing_branches'] for r in report['missing_by_surface'].values()) == 1
    assert report['files'][1]['missing_branches'][0]['to']['exit']


def test_mismatched_source_and_foreign_coverage_rejected(measured, tmp_path):
    data, root, manifest = measured
    (root / 'scripts/a.py').write_text('changed = True\n')
    with pytest.raises(ValueError, match='baseline mismatch'):
        inventory(data, root, root, 'parent_only', manifest)
    altered = deepcopy(data)
    altered['files'] = {str(tmp_path / 'foreign.py'): next(iter(data['files'].values()))}
    with pytest.raises(ValueError):
        inventory(altered, root, root, 'parent_only', manifest)


def test_inconsistent_totals_rejected(measured):
    data, root, manifest = measured
    data['totals'] = {**data['totals'], 'missing_lines': 99}
    with pytest.raises(ValueError, match='totals differ'):
        inventory(data, root, root, 'parent_only', manifest)
