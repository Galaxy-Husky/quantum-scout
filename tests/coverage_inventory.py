"""Read-only coverage inventory: source area and static CLI surface are separate axes.

No imports of measured code, no execution, and no inference of subprocess coverage.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


COUNTS = ('covered_lines', 'num_statements', 'missing_lines',
          'covered_branches', 'num_branches', 'missing_branches')


def summary(rows):
    result = {key: sum(row[key] for row in rows) for key in COUNTS}
    for label, covered, total in [('line', 'covered_lines', 'num_statements'),
                                   ('branch', 'covered_branches', 'num_branches')]:
        result[label + '_percent'] = (100 * result[covered] / result[total]
                                      if result[total] else None)
    return result


def source_map(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    owners, cli = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, node.end_lineno + 1):
                owners.setdefault(line, node.name)
            if node.name == 'main':
                cli.update(range(node.lineno, node.end_lineno + 1))
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Compare)
                and ast.dump(node.test) in {
                    ast.dump(ast.parse("__name__ == '__main__'", mode='eval').body),
                    ast.dump(ast.parse("'__main__' == __name__", mode='eval').body)}):
            cli.update(range(node.lineno, node.end_lineno + 1))
    return owners, cli


def inventory(data, skill_root, coverage_root, process_scope, manifest):
    if process_scope not in {'parent_only', 'subprocess_included'}:
        raise ValueError('Explicit process scope required')
    skill_root, coverage_root = Path(skill_root).resolve(), Path(coverage_root).resolve()
    if not data['meta']['branch_coverage']:
        raise ValueError('Branch coverage JSON required')
    rows = []
    for filename, measured in sorted(data['files'].items()):
        path = Path(filename).resolve()
        relative = path.relative_to(coverage_root).as_posix()
        source = skill_root / relative
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        if manifest.get(relative) != sha:
            raise ValueError('Source baseline mismatch: ' + relative)
        owners, cli = source_map(source)
        counts = {key: measured['summary'][key] for key in COUNTS}
        if (counts['missing_lines'] != len(measured['missing_lines'])
                or counts['missing_branches'] != len(measured['missing_branches'])):
            raise ValueError('Inconsistent coverage counts: ' + relative)
        def location(line):
            return {'line': line, 'owner': owners.get(abs(line), '<module>'),
                    'surface': 'cli_entry' if abs(line) in cli else 'other',
                    'exit': line < 0}
        rows.append({'file': relative, 'source_sha256': sha,
                     'area': 'scripts' if relative.startswith('scripts/') else
                             'assets' if relative.startswith('assets/') else 'other',
                     'counts': counts,
                     'missing_lines': [location(line) for line in measured['missing_lines']],
                     'missing_branches': [{'from': location(a), 'to': location(b)}
                                          for a, b in measured['missing_branches']]})
    total = summary([r['counts'] for r in rows])
    if any(total[key] != data['totals'][key] for key in COUNTS):
        raise ValueError('File totals differ from coverage totals')
    by_surface = {name: {
        'missing_lines': sum(item['surface'] == name for r in rows for item in r['missing_lines']),
        'missing_branches': sum(item['from']['surface'] == name
                                for r in rows for item in r['missing_branches'])}
        for name in ('cli_entry', 'other')}
    callsites = []
    for directory in ('scripts', 'assets', 'tests'):
        for path in sorted((skill_root / directory).rglob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if isinstance(node, ast.Call):
                    function = ast.unparse(node.func)
                    if function in {'subprocess.run', 'subprocess.Popen', 'subprocess.check_output',
                                    'subprocess.check_call', 'asyncio.create_subprocess_exec',
                                    'asyncio.create_subprocess_shell'}:
                        callsites.append({'file': path.relative_to(skill_root).as_posix(),
                                          'line': node.lineno, 'call': function})
    return {'coverage_meta': data['meta'], 'process_scope': process_scope,
            'scope_note': 'Static CLI surface is main()/__main__ only, not all code reachable from CLI. '
                          'Subprocess callsites are syntactic references, not proof of child execution '
                          'or measured coverage. Missing parent execution does not imply unreachable code.',
            'totals': total, 'by_area': {area: summary([r['counts'] for r in rows if r['area'] == area])
                                       for area in ('scripts', 'assets', 'other')},
            'missing_by_surface': by_surface, 'subprocess_callsites': callsites, 'files': rows}


def markdown(report):
    lines = ['# Coverage inventory', '', report['scope_note'], '',
             'Process scope: ' + report['process_scope'], '',
             '| Area | Covered/statements | Missing lines | Covered/branches | Missing branches |',
             '|---|---:|---:|---:|---:|']
    for area, c in report['by_area'].items():
        lines.append(f"| {area} | {c['covered_lines']}/{c['num_statements']} | {c['missing_lines']} | "
                     f"{c['covered_branches']}/{c['num_branches']} | {c['missing_branches']} |")
    lines += ['', '| Static surface | Missing lines | Missing branches (origin) |', '|---|---:|---:|']
    for surface, c in report['missing_by_surface'].items():
        lines.append(f"| {surface} | {c['missing_lines']} | {c['missing_branches']} |")
    for row in sorted(report['files'], key=lambda r: (-r['counts']['missing_lines'], r['file'])):
        lines += ['', '## ' + row['file'], '',
                  'Missing lines: ' + ', '.join(f"{x['line']} ({x['owner']}; {x['surface']})"
                                               for x in row['missing_lines']),
                  '', 'Missing branches: ' + ', '.join(f"{b['from']['line']}→{b['to']['line']}"
                                                      for b in row['missing_branches'])]
    lines += ['', '## Subprocess callsites (static inventory)', '']
    lines += [f"- {r['file']}:{r['line']} {r['call']}" for r in report['subprocess_callsites']]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('coverage_json', type=Path)
    parser.add_argument('--skill-root', type=Path, required=True)
    parser.add_argument('--coverage-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--process-scope', choices=['parent_only', 'subprocess_included'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = inventory(json.loads(args.coverage_json.read_text()), args.skill_root,
                       args.coverage_root, args.process_scope, json.loads(args.manifest.read_text()))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'inventory.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.output / 'inventory.md').write_text(markdown(report))
    print(json.dumps({'totals': report['totals'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
