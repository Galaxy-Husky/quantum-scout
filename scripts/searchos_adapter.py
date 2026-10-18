#!/usr/bin/env python3
# State ownership and upstream API contract: references/workflow.md
"""Local Quantum Scout adapter for SearchOS SOCM; no model or search calls."""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import warnings

from schema_generator import SKILL_ROOT, TRACK_SKILLS, digest, domain_config, generate, write_strategy_skills
from review_policy import find_decision, bound, attributed, supported_pair, source_depth, nonempty, source_reviewable, citation_allowed, review_accepted
from searchos_project import ProjectLayout, WorkspaceLayout
from searchos.skills.catalog.registry import SkillRegistry
from searchos.skills.runtime.executor_runtime import ExecutionPolicy, run_executor
from searchos.socm.coverage import CellStatus, ColumnDesc
from searchos.socm.evidence import EvidenceNode
from searchos.socm.frontier import FrontierTask, FrontierTaskStatus, MAX_FRONTIER_CAP
from searchos.socm.state import SearchState
from searchos.socm.workspace import WorkspaceManager


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def locked(path):
    with (Path(path) / '.quantum.lock').open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def key(table, case, field):
    return f'{table}/{case}.{field}'


def legacy_values(batch, config):
    values = {}
    for case in batch.get('cases', []):
        cid = case['case_id']
        for field in config['fields']:
            record = case.get('problem_definition', {}).get(field, {})
            values[key('problem_definition', cid, field)] = {'value': record.get('value_text'),
                                                           'reason': record.get('reason'), 'record': record}
        for track, evaluation in case.get('tracks', {}).items():
            if track not in config['tracks']:
                raise ValueError('unknown legacy track: ' + track)
            for criterion, value in evaluation.get('criteria', {}).items():
                if criterion not in config['tracks'][track]['admission_criteria']:
                    raise ValueError('unknown criterion: ' + criterion)
                values[key(track + '_admission', cid, criterion)] = {'value': value}
            for dimension, record in evaluation.get('scores', {}).items():
                if dimension not in config['tracks'][track]['scoring_dimensions']:
                    raise ValueError('unknown dimension: ' + dimension)
                value = record.get('score') if isinstance(record, dict) else record
                values[key(track + '_scoring', cid, dimension)] = {'value': value}
    return values


def value_text(value):
    if type(value) is bool:
        return str(value).lower()
    return str(value)


def task_claims(meta):
    """Read ownership without modifying legacy workspaces."""
    claims = meta.get('claimed_tasks', {})
    if isinstance(claims, dict):
        return claims
    invocations = meta.get('online', {}).get('invocations', [])
    return {task_id: {'owner': next((i['started_at'] for i in reversed(invocations)
        if i.get('status') == 'running' and i.get('active_task') == task_id), 'manual'),
        'started_at': None} for task_id in claims}


def claim_task(meta, task_id, owner):
    claims = dict(task_claims(meta))
    if task_id in claims:
        raise ValueError('Task already claimed')
    claims[task_id] = {'owner': owner, 'started_at': now()}
    meta['claimed_tasks'] = claims


def release_claim(meta, task_id):
    claims = dict(task_claims(meta))
    del claims[task_id]
    meta['claimed_tasks'] = claims


def project(meta, *, with_tasks=True):
    """Rebuild the SearchOS scheduling projection from the adapter's audit facts."""
    state = SearchState(intent=meta['intent'])
    coverage = state.coverage_map
    for table in meta['schema']['tables']:
        coverage.add_table(**{**table, 'column_desc': {k: ColumnDesc(**v) for k, v in table['column_desc'].items()}})
    for cell_id, old in meta['legacy_values'].items():
        if old.get('value') is not None and old.get('value') != 'insufficient_evidence':
            coverage.cells[cell_id].status = CellStatus.UNCERTAIN
            coverage.cells[cell_id].display_hint = value_text(old['value'])
    for cell_id in meta.get('gaps', {}):
        coverage.cells[cell_id].status = CellStatus.MISSING
    for report_id, entry in meta['grounding'].items():
        request, report = entry['request'], entry['report']
        table_id = request['table_id']
        for candidate in report['validated_candidates']:
            cell_id = key(table_id, candidate['case_id'], candidate['field'])
            cell = coverage.cells[cell_id]
            if cell.status != CellStatus.FILLED:
                cell.status = CellStatus.UNCERTAIN
                cell.display_hint = value_text(candidate['value_text'])
    # Both independent decisions must pass; legacy semantic-only facts stay UNCERTAIN.
    supported = {}
    for review in meta['reviews']:
        entry = meta['grounding'][review['report_id']]
        request = entry['request']
        candidate = entry['report']['validated_candidates'][review['candidate_index']]
        cell_id = key(request['table_id'], candidate['case_id'], candidate['field'])
        attribution = find_decision(meta, 'attributions', review['report_id'], review['candidate_index'])
        if not review_accepted(meta, attribution, review, candidate, request['source']):
            continue
        value = value_text(candidate['value_text'])
        supported.setdefault(cell_id, []).append((value, review, candidate, request))
    for cell_id, claims in supported.items():
        cell = coverage.cells[cell_id]
        fact_ids = set()
        for value, review, candidate, request in claims:
            receipt = candidate['grounding']
            evidence_id = 'qs_' + digest([review['report_id'], review['candidate_index']])[:24]
            source = request['source'].get('url') or request['source']['source_id']
            identity = (review['report_id'], review['candidate_index'])
            if identity in fact_ids:
                continue
            fact_ids.add(identity)
            # Preserve case-sensitive scientific values and document versions.
            # Upstream add_node lowercases values and omits the text hash.
            state.evidence_graph.nodes.append(EvidenceNode(id=evidence_id, finding=value, value=value,
                source=source,
                source_excerpt=candidate['quote'], confidence={'low': .4, 'medium': .6}[candidate['confidence']],
                table_id=request['table_id'], entity=candidate['case_id'], attribute=candidate['field'],
                alignment='full', alignment_note='Independent ' + review['reviewer_kind'] + ' review: ' + review['reason'],
                span=tuple(receipt['span']), text_hash=receipt['source_sha256']))
            cell.supporting_evidence_ids.append(evidence_id)
    # Human decisions also apply when their formerly eligible evidence has disappeared.
    from aggregation import resolve
    for cell_id in set(supported) | {d['cell_id'] for d in meta.get('aggregations', [])}:
        cell = coverage.cells[cell_id]
        result = resolve(meta, cell_id)
        selected = result['selected']
        cell.supporting_evidence_ids = ([selected['binding']['evidence_id']] if selected else
            [item['binding']['evidence_id'] for item in result['remaining']])
        cell.status = CellStatus.FILLED if selected else CellStatus.UNCERTAIN
        cell.best_alignment = 'full' if selected else 'partial'
        cell.display_hint = (value_text(selected['candidate']['value_text']) if selected else
                             'aggregation_pending' if result['outcome'] == 'pending' else 'aggregation_rejected')
    if with_tasks:
        from online_policy import action_plan
        for item in action_plan(meta, state)['actions']:
            status = (FrontierTaskStatus.RUNNING if 'task_claimed' in item['blocked_reasons'] else
                      FrontierTaskStatus.BLOCKED if item['blocked_reasons'] else FrontierTaskStatus.PENDING)
            if len(state.frontier.questions) >= MAX_FRONTIER_CAP:
                raise ValueError('Frontier capacity exceeded; use a smaller explicit case scope')
            state.frontier.add(FrontierTask(**item['task'], status=status,
                blocked_by=item['blocked_reasons']))
    return state


def persist(path, meta):
    state = project(meta)  # validate before committing any facts
    write_json(WorkspaceLayout(path).adapter, meta)
    write_json(WorkspaceLayout(path).schema, meta['schema'])
    workspace = WorkspaceManager(WorkspaceLayout(path).socm.parent, WorkspaceLayout(path).socm.name)
    workspace.save_state(state)
    workspace.save_coverage_map()
    return state


def prepare(path, batch=None, case_ids=None, config_dir=SKILL_ROOT / 'config'):
    config = domain_config(config_dir)
    batch = batch or {}
    case_ids = case_ids or [c['case_id'] for c in batch.get('cases', [])]
    if not case_ids:
        raise ValueError('Provide --case-id or a batch containing cases')
    schema = generate(case_ids, config)
    meta = {'version': 2, 'run_id': path.name, 'intent': 'Quantum Scout evidence gap scheduling',
            'prepared_at': now(), 'research_started': False, 'config': config, 'schema': schema,
            'case_ids': case_ids, 'source_batch_run_id': batch.get('run_id'),
            'source_batch_sha256': digest(batch) if batch else None,
            'legacy_values': legacy_values(batch, config), 'grounding': {}, 'attributions': [], 'reviews': [], 'attribution_checks': [], 'claimed_tasks': {}}
    project(meta)
    path.mkdir(parents=True, exist_ok=False)
    workspace = WorkspaceManager(WorkspaceLayout(path).socm.parent, WorkspaceLayout(path).socm.name); workspace.create()
    write_strategy_skills(path / 'skills', config)
    shutil.copytree(SKILL_ROOT / 'assets/quantum_grounding',
                    path / 'skills/access/quantum_grounding', ignore=shutil.ignore_patterns('__pycache__'))
    with locked(path):
        return persist(path, meta)


def load(path):
    try:
        meta = json.loads(WorkspaceLayout(path).adapter.read_text())
    except FileNotFoundError as exc:
        raise ValueError('Current workspace requires state/quantum_adapter.json; prepare a new workspace') from exc
    except json.JSONDecodeError as exc:
        raise ValueError('Invalid workspace JSON; restore a valid checkpoint') from exc
    if not isinstance(meta, dict) or type(meta.get('version')) is not int or meta['version'] != 2:
        raise ValueError('Unsupported workspace version; prepare a new version-2 workspace')
    try:
        valid_digest = meta['schema']['config_sha256'] == digest(meta['config'])
    except (KeyError, TypeError) as exc:
        raise ValueError('Workspace configuration or digest is missing') from exc
    if not valid_digest:
        raise ValueError('Adapter config digest mismatch')
    current = digest(domain_config())
    if meta['schema']['config_sha256'] != current:
        warnings.warn('Workspace config differs from installed domain config; retaining workspace snapshot', RuntimeWarning, stacklevel=2)
    return meta


def summary(state):
    counts = {s.value: 0 for s in CellStatus}
    for cell in state.coverage_map.cells.values():
        counts[cell.status.value] += 1
    return {'coverage_role': 'scheduling_only', 'semantic_verifier': 'unavailable',
            'total_cells': len(state.coverage_map.cells), **counts,
            'evidence_nodes': len(state.evidence_graph.nodes),
            'frontier_tasks': len(state.frontier.questions),
            'ready_tasks': sum(t.status == FrontierTaskStatus.PENDING for t in state.frontier.questions),
            'blocked_tasks': sum(t.status == FrontierTaskStatus.BLOCKED for t in state.frontier.questions),
            'running_tasks': sum(t.status == FrontierTaskStatus.RUNNING for t in state.frontier.questions),
            'stop_reason': None}


def ground(path, request):
    with locked(path):
        meta = load(path)
        if request.get('run_id') != meta['run_id'] or not request.get('extractor_id'):
            raise ValueError('run_id must match workspace, extractor_id is required')
        table = next((t for t in meta['schema']['tables'] if t['table_id'] == request.get('table_id')), None)
        if table is None or not request.get('evidence'):
            raise ValueError('known table_id and nonempty evidence required')
        identities = set()
        for item in request['evidence']:
            identity = (item.get('case_id'), item.get('field'))
            if identity in identities or identity[0] not in meta['case_ids'] or identity[1] not in table['attributes']:
                raise ValueError('unknown or duplicate case/field in request')
            identities.add(identity)
            if item.get('value_text') is None or not value_text(item['value_text']).strip():
                raise ValueError('candidate value_text is required')
            if request['table_id'] == 'problem_definition' and not isinstance(item['value_text'], str):
                raise ValueError('problem definition value_text must be a string')
            applicability = item.get('coverage_status', 'covered')
            if applicability not in {'covered', 'not_applicable'}:
                raise ValueError('Invalid candidate coverage_status')
            if applicability == 'not_applicable' and (request['table_id'] != 'problem_definition'
                    or not item.get('applicability_reason', '').strip()):
                raise ValueError('Not-applicable requires a justified problem-definition candidate')
            check = ColumnDesc(**table['column_desc'][item['field']]).check
            if check and check.violation(value_text(item['value_text'])):
                raise ValueError('value violates domain column check')
            if value_text(item['value_text']) == 'insufficient_evidence':
                raise ValueError('absence of evidence is a gap, not a supported claim')
            if item.get('evidence_level') not in {'primary', 'secondary'} or item.get('confidence') not in {'low', 'medium'}:
                raise ValueError('candidate needs evidence_level and low/medium single-source confidence')
        report_id = digest(request)
        if report_id in meta['grounding']:
            return {'report_id': report_id, **meta['grounding'][report_id]['report']}
        result = asyncio.run(run_executor(path / 'skills/access/quantum_grounding', request,
                                         policy=ExecutionPolicy(timeout_s=10)))
        if result.get('error'):
            raise RuntimeError(result['error_type'] + ': ' + result['error'])
        if request['source'].get('citation_identity', {}).get('state') == 'mismatch':
            for c in result['validated_candidates']:
                result['grounding_failures'].append({'case_id': c['case_id'], 'field': c['field'],
                    'source_id': c['source_id'], 'failure_type': 'citation_mismatch', 'candidate': c,
                    'citation_identity': request['source']['citation_identity']})
        meta['grounding'][report_id] = {'request': request, 'report': result, 'recorded_at': now()}
        meta['research_started'] = True
        persist(path, meta)
        return {'report_id': report_id, **result}


def decision_candidate(meta, decision):
    entry = meta['grounding'][decision['report_id']]
    index = decision['candidate_index']
    if type(index) is not int or not 0 <= index < len(entry['report']['validated_candidates']):
        raise ValueError('candidate_index must refer to a grounded candidate')
    candidate = entry['report']['validated_candidates'][index]
    if not bound(decision, candidate) or decision['reviewer_id'] == entry['request']['extractor_id']:
        raise ValueError('Independent decision must bind exact case, claim, location and source hash')
    return entry, candidate


def attribute(path, decision):
    with locked(path):
        meta = load(path)
        entry, candidate = decision_candidate(meta, decision)
        if decision.get('attribution') not in {'attributed', 'abstained', 'absent'} or not nonempty(decision.get('attribution_reason')):
            raise ValueError('Attribution requires an explicit verdict and reason')
        if find_decision(meta, 'attributions', decision['report_id'], decision['candidate_index']):
            raise ValueError('Candidate already attributed; submit a new candidate for revision')
        # Source depth is provenance supplied by the runtime, never an LLM claim.
        meta.setdefault('attributions', []).append({**decision,
            'source_depth': source_depth(meta, entry['request']['source']), 'recorded_at': now()})
        return summary(persist(path, meta))


def review(path, decision):
    with locked(path):
        meta = load(path)
        entry, candidate = decision_candidate(meta, decision)
        attribution = find_decision(meta, 'attributions', decision['report_id'], decision['candidate_index'])
        if not attributed(attribution, candidate) or attribution['reviewer_id'] == decision['reviewer_id']:
            raise ValueError('Semantic review requires a separate attributed decision')
        if (decision.get('verdict') not in {'supported', 'semantic_mismatch', 'abstain'}
                or type(decision.get('location_checked')) is not bool
                or decision.get('domain_rule_met') not in {'met', 'not_met', 'unclear'}
                or not nonempty(decision.get('domain_rule_reason')) or not nonempty(decision.get('reason'))):
            raise ValueError('Semantic review requires verdict, location check and domain-rule decision')
        if find_decision(meta, 'reviews', decision['report_id'], decision['candidate_index']):
            raise ValueError('Candidate already reviewed; submit a new candidate for revision')
        # Keep abstentions and inconsistent model outputs in the audit; project
        # enforces all four acceptance conditions without rewriting the verdict.
        meta['reviews'].append({**decision, 'recorded_at': now()})
        return summary(persist(path, meta))


def audit_attribution(path, decision, post_hoc=False):
    with locked(path):
        meta = load(path)
        _, candidate = decision_candidate(meta, decision)
        a = find_decision(meta, 'attributions', decision['report_id'], decision['candidate_index'])
        review = find_decision(meta, 'reviews', decision['report_id'], decision['candidate_index'])
        if (not supported_pair(a, review, candidate) or decision.get('reviewer_kind') != 'human'
                or type(decision.get('attribution_correct')) is not bool or not nonempty(decision.get('reason'))):
            raise ValueError('Human attribution audit must sample a dual-reviewed supported candidate')
        if find_decision(meta, 'attribution_checks', decision['report_id'], decision['candidate_index']):
            raise ValueError('Candidate already sampled')
        if not post_hoc:
            entry = meta['grounding'][decision['report_id']]
            cell = key(entry['request']['table_id'], candidate['case_id'], candidate['field'])
            if project(meta).coverage_map.cells[cell].status.value != 'filled':
                raise ValueError('Candidate is not on the current coverage chain; use --post-hoc')
            from coverage_policy import reviewed_cases, case_evidence
            current = reviewed_cases(meta, project(meta))
            refs = (ref for case in current for ref in case_evidence(case))
            if not any(v.get('semantic_review', {}).get('report_id') == decision['report_id']
                       and v['semantic_review']['candidate_index'] == decision['candidate_index'] for v in refs):
                raise ValueError('Candidate is not on the current coverage chain; use --post-hoc')
        meta.setdefault('attribution_checks', []).append({**decision, 'recorded_at': now()})
        state = persist(path, meta)
        from coverage_policy import reviewed_cases
        cases = reviewed_cases(meta, state)
        return {**summary(state), 'human_audit_status': {c['case_id']: c['human_audit_status'] for c in cases}}


def record_gap(path, gap):
    with locked(path):
        meta = load(path)
        cell_id = key(gap['table_id'], gap['case_id'], gap['field'])
        state = project(meta)
        if cell_id not in state.coverage_map.cells or not gap.get('reason'):
            raise ValueError('A known cell and explicit missing reason are required')
        if gap.get('status') not in {'missing', 'hard_cell'}:
            raise ValueError('Gap status must be missing or hard_cell')
        if gap['status'] == 'hard_cell' and not gap.get('attempts'):
            raise ValueError('Unreachable cells require access/query attempt records')
        if state.coverage_map.cells[cell_id].status == CellStatus.FILLED:
            raise ValueError('Cannot hide reviewed evidence by marking a gap')
        recorded = {k: v for k, v in gap.items() if k != 'status'}
        recorded.update(investigate=gap['status'] != 'hard_cell', recorded_at=now())
        meta.setdefault('gaps', {})[cell_id] = recorded
        meta.setdefault('gap_history', []).append(meta['gaps'][cell_id])
        return summary(persist(path, meta))


def add_citation_results(path, node_id, results):
    """The only citation task write path; enforce roots, dedup, cap and dependencies."""
    from citation_backends import aliases, identity
    from searchos_network import public_url
    with locked(path):
        meta = load(path)
        state = project(meta)
        node = next(n for n in state.evidence_graph.nodes if n.id == node_id)
        cell = state.coverage_map.cells[key(node.table_id, node.entity, node.attribute)]
        if cell.status != CellStatus.FILLED:
            raise ValueError('Citation parent must belong to an unconflicted FILLED cell')
        sources = meta.get('online', {}).get('sources', {})
        source = next((r for r in sources.values() if r.get('source', {}).get('url') == node.source
                       or r.get('source', {}).get('source_id') == node.source), None)
        if not source or source.get('citation_depth', 0) != 0:
            raise ValueError('Citation expansion requires an opened depth-zero parent')
        tasks = meta.setdefault('citation_tasks', {})
        existing = [t for t in tasks.values() if t['parent_node_id'] == node_id]
        from online_policy import action_plan
        proposals = action_plan(meta, state)['actions']
        capacity = min(5 - len(existing), MAX_FRONTIER_CAP - len(proposals))
        bases = [item['task'] for item in proposals if item['task'].get('kind', 'search') == 'search'
                 and item['task']['target_cells'][0].split('/', 1)[1].split('.', 1)[0] == node.entity]
        if not bases or capacity <= 0:
            return []
        base = max(bases, key=lambda t: t['priority'])
        seen = {identity(r['url']) for r in sources.values()}
        seen.update(identity(h['url']) for r in meta.get('online', {}).get('searches', {}).values()
                    for h in r.get('results', []))
        for t in tasks.values():
            seen.update(t['aliases'])
        added = []
        for hit in results:
            names = aliases(hit)
            if seen & names:
                continue
            public_url(hit['url'])
            task_id = 'cite_' + digest([node.entity, sorted(names)])[:20]
            record = {**hit, 'id': task_id, 'aliases': sorted(names), 'case_id': node.entity,
                      'base_task_id': base['id'], 'base_task': base, 'parent_node_id': node_id, 'depth': 1,
                      'status': 'pending', 'created_at': now()}
            tasks[task_id] = record
            added.append(record)
            seen.update(names)
            if len(added) >= capacity:
                break
        persist(path, meta)
        return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('prepare'); init.add_argument('workspace', type=Path, nargs='?')
    init.add_argument('--project-root', type=Path, default=Path.cwd())
    init.add_argument('--batch', type=Path); init.add_argument('--case-id', action='append')
    init.add_argument('--config-dir', type=Path, default=SKILL_ROOT / 'config')
    add = sub.add_parser('add-case'); add.add_argument('workspace', type=Path)
    add.add_argument('--case-id', action='append', required=True)
    release = sub.add_parser('release-task'); release.add_argument('workspace', type=Path)
    release.add_argument('task_id'); release.add_argument('--reason', required=True)
    aggregation = sub.add_parser('aggregation-context'); aggregation.add_argument('workspace', type=Path)
    aggregation.add_argument('cell_id')
    selection = sub.add_parser('aggregate-field'); selection.add_argument('workspace', type=Path)
    selection.add_argument('request', type=Path)
    for command in ('summary', 'next-task', 'repair', 'ground', 'attribute', 'review', 'audit-attribution', 'record-gap'):
        child = sub.add_parser(command); child.add_argument('workspace', type=Path)
        if command in {'ground', 'attribute', 'review', 'audit-attribution', 'record-gap'}: child.add_argument('request', type=Path)
        if command == 'audit-attribution': child.add_argument('--post-hoc', action='store_true')
    args = parser.parse_args()
    path = (args.workspace or ProjectLayout(args.project_root).new_workspace('session')).resolve()
    if args.command == 'aggregation-context':
        from aggregation import context
        with locked(path):
            output = context(load(path), args.cell_id)
    elif args.command == 'aggregate-field':
        from aggregation import record
        output = record(path, json.loads(args.request.read_text()))
    elif args.command == 'prepare':
        if args.batch and args.case_id: parser.error('Use --batch or --case-id, not both')
        batch = json.loads(args.batch.read_text()) if args.batch else None
        state = prepare(path, batch, args.case_id, args.config_dir)
        registry = SkillRegistry(); count = registry.load_directory(path / 'skills')
        output = {**summary(state), 'registered_skills': count, 'workspace': str(path)}
    elif args.command in {'ground', 'attribute', 'review', 'audit-attribution', 'record-gap'}:
        output = {'ground': ground, 'attribute': attribute, 'review': review, 'audit-attribution': audit_attribution, 'record-gap': record_gap}[args.command](path, json.loads(args.request.read_text()), **({'post_hoc': args.post_hoc} if args.command == 'audit-attribution' else {}))
    else:
        with locked(path):
            meta = load(path); state = project(meta)
            if args.command == 'add-case':
                if 'online' in meta:
                    raise ValueError('Online case scope is fixed; use a new workspace')
                ids = meta['case_ids'] + args.case_id
                meta['schema'] = generate(ids, meta['config']); meta['case_ids'] = ids
                output = summary(persist(path, meta))
            elif args.command == 'release-task':
                if args.task_id not in task_claims(meta) or not args.reason.strip():
                    raise ValueError('Known claimed task and retry reason required')
                release_claim(meta, args.task_id)
                meta.setdefault('task_releases', []).append({'id': args.task_id, 'reason': args.reason, 'at': now()})
                output = summary(persist(path, meta))
            elif args.command == 'next-task':
                from online_policy import action_plan
                task = next(iter(action_plan(meta, state)['executable_actions']), None)
                if task:
                    claim_task(meta, task['id'], 'manual'); persist(path, meta)
                output = task if task else {'task': None, 'stop_reason': None}
            elif args.command == 'repair': output = summary(persist(path, meta))
            else: output = summary(state)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
