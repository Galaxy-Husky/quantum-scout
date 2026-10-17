#!/usr/bin/env python3
"""Render calibration batch and case views from the document-shaped batch JSON."""
import argparse, json
from pathlib import Path
from classify_source import classify_source_role, case_references_source
# Re-export existing entry points for historical callers.
from validate_batch import (
    WARNING_CATEGORIES, SUCCESS_STOPS, INCOMPLETE_STOPS, LEGACY_STOP,
    criterion_is_true, admission_is_passed, warning, accepted_tracks, accepted_cases,
    validate_admission_consistency, validate_structure, validate_adaptive_queries,
    validate_search_adequacy, validate_operational_stop, validate_completion_guard,
    evidence_breakdown_warnings,
)

def render_case_evidence(case, sources, failures=()):
    """Human view of the same selected evidence; no separate preview fact."""
    from html import escape
    rows = list(case.get('problem_definition', {}).items())
    for track, evaluation in case.get('tracks', {}).items():
        for collection in ('criteria_evidence', 'score_evidence'):
            rows.extend((track + '/' + field, evidence)
                        for field, evidence in evaluation.get(collection, {}).items())
    for failure in failures:
        if failure.get('case_id') == case.get('case_id') and failure.get('failure_type') == 'semantic_mismatch':
            rows.append(('未接受候选/' + failure.get('field', ''),
                         {**failure['candidate'], 'semantic_review': failure.get('review', {})}))
    lines = []
    for field, evidence in rows:
        lines += ['', '### ' + escape(field), '', escape(str(evidence.get('value_text') or '缺证／尚未完成'))]
        if not evidence.get('quote'):
            continue
        source = sources.get(evidence.get('source_id'), {})
        url = source.get('url', '')
        label = escape(str(evidence.get('source_id', '')))
        if isinstance(url, str) and url.startswith(('https://', 'http://')):
            label = '<a href="' + escape(url, quote=True) + '">' + label + '</a>'
        lines += ['', '来源：' + label + '；位置：' + escape(str(evidence.get('location', ''))),
                  '版本：' + escape(str(source.get('document_version', '未记录')))]
        receipt = evidence.get('grounding') or {}
        if receipt:
            lines += ['原文偏移：' + escape(str(receipt.get('span'))) +
                      '；SHA256：' + escape(str(receipt.get('source_sha256')))]
        def passage(text, title):
            # Escape body HTML rather than treating untrusted document text as markup.
            opened = ' open' if len(text) <= 600 else ''
            return ['', '<details' + opened + '><summary>' + escape(title) + '</summary>', '',
                    '<pre>' + escape(text) + '</pre>', '', '</details>', '']
        lines += passage(evidence['quote'], '所选完整原文证据（与机器评审一致）')
        # Explicit ContextGem references are also supplied to the machine review.
        seen = {' '.join(evidence['quote'].split())}
        for ref in evidence.get('references', []):
            text = ref.get('text', '')
            if text and ' '.join(text.split()) not in seen:
                seen.add(' '.join(text.split()))
                lines += ['关联位置：' + escape(str(ref.get('location', '')))]
                lines += passage(text, '模型明确引用的关联原文')
        review = evidence.get('semantic_review') or {}
        lines += ['语义结论：' + escape(str(review.get('verdict', '未记录'))),
                  '评审理由：' + escape(str(review.get('reason', '未记录')))]
        search = review.get('counter_evidence_search') or {}
        for group, title in (('negation_evidence', '否定'), ('conditional_limits_evidence', '条件'),
                             ('threat_model_boundary_evidence', '威胁边界'), ('contradictions_found', '矛盾')):
            for finding in search.get(group, []):
                lines += ['', title + '：' + escape(str(finding.get('reason', '未记录'))),
                          '位置：' + escape(str(finding.get('location', '')))]
                lines += passage(finding.get('quote', ''), title + '的完整原文证据')
    return lines


def pct(value):
    return "N/A" if value is None else f"{value:.1%}"

def score_text(value):
    return "N/A" if value is None else f"{value:.2f}"

def format_warning(item):
    return f"[{item.get('category','unknown')}] {item.get('message','')}" if isinstance(item,dict) else str(item)

def human_audit_text(case):
    status = case.get('human_audit_status', 'unverified')
    label = {'unverified': '人工未抽查', 'partial': '人工部分抽查', 'verified': '人工已验证',
             'rejected': '人工已拒绝', 'not_applicable': '人工审计不适用'}[status]
    return f'{label}（{status}，当前派生状态）'

def discovery_trail(case):
    """An unlinked online trail is a list; never invent a query association."""
    trail = case.get('discovery_trail')
    return trail if isinstance(trail, dict) else {}

def failure_context(evaluation, minimum_score=15):
    """Make failure_class semantics explicit in human-readable views."""
    failure = evaluation.get("failure_class")
    passed = admission_is_passed(evaluation.get("passed_admission"))
    score = evaluation.get("score_normalized")
    if passed and (score is None or score < minimum_score):
        return f"评分失败：{failure or 'insufficient_evidence'}"
    if not passed:
        return f"准入失败：{failure or 'failed_admission'}"
    return "—"

def render(data, legacy_audit=False):
    validate_admission_consistency(data)
    validate_structure(data)
    validate_adaptive_queries(data)
    validate_search_adequacy(data, legacy_audit)
    validate_completion_guard(data, legacy_audit)
    counts=data["counts"]; quality=data["quality"]; progress=data["checkpoint"].get("search_progress",{})
    stop=data["stop_reason"]
    status = "✅ completed" if data["run_status"] == "completed" else data["run_status"]
    if stop in INCOMPLETE_STOPS: status = "⚠️ incomplete"
    if stop == LEGACY_STOP: status = "⚠️ historical / unverified"
    pool=counts.get("discovery_pool_size",counts.get("discovery_sources",0)); limit=counts.get("discovery_limit")
    saturation=(pool/limit) if isinstance(limit,(int,float)) and limit else None
    good=accepted_cases(data)
    evidence_sources=[
        s for s in data["sources"]
        if s.get("status") == "opened" and (s.get("evidence") or any(
            case_references_source(case, s.get("source_id"))
            for case in data.get("cases", [])
        ))
    ]
    quality_warnings = evidence_breakdown_warnings(data)
    lines=[f"# Pilot 批次报告：{data['run_id']}","",f"**状态**：{status}（`{stop}`）","","## 一、执行摘要","",f"- 发现池：{pool} / 上限 {limit if limit is not None else 'N/A'}（饱和度 {pct(saturation)}）",f"- 来源：发现 {counts.get('discovery_sources','N/A')}，尝试 {counts.get('attempted_sources','N/A')}，成功打开 {counts.get('opened_sources','N/A')}，仅元数据 {counts.get('opened_metadata_only','N/A')}，未尝试 {counts.get('sources_unattempted','N/A')}",f"- 案例：候选 {counts.get('extracted_candidate_cases','N/A')}，问题定义完成 {counts.get('problem_definition_complete_cases','N/A')}，纳入 {counts.get('accepted_cases','N/A')}",f"- 通过 Track：{', '.join(sorted({t for c in good for t in accepted_tracks(c, data.get("config_snapshot"))})) or '无'}"]
    if stop == 'error':
        lines.append(f"- 错误细分类：{data['checkpoint'].get('operational_cause') or data['checkpoint'].get('stop_evidence', {}).get('error_kind', 'unknown')}。")
    limits = quality.get('limit_policy')
    if limits:
        lines.append(f"- 在线限制来源：{limits['owner']}；stall_rounds={limits['effective']['stall_rounds']}；"
                     f"phase {limits.get('phase')} 的参考阈值={limits['phase_reference'].get('diminishing_returns_threshold')}（未应用）。")
    rejected = quality.get('contract_rejections')
    if rejected:
        lines.append(f"- 契约拒绝：本次 {rejected['invocation_candidates']} 条；累计 {rejected['candidates']} 条，涉及 {rejected['affected_calls']} 次调用（含部分有效输出，不等于整次浪费）。")
    if stop == 'budget_exhausted':
        cause = data['checkpoint'].get('operational_cause') or data['checkpoint'].get('stop_evidence', {}).get('budget_cause')
        meaning = {'round_limit': '轮次上限，不是模型调用上限', 'model_call_limit': '模型调用上限',
                   'wall_clock_limit': '运行时间上限'}.get(cause, cause)
        lines.append(f'- 预算停止细分类：{meaning}（{cause}）。')
    hard_fields = {'parties_and_roles', 'real_world_problem', 'constraints', 'quantum_mechanism_role'}
    from schema_generator import domain_config
    fields = (data.get('config_snapshot') or domain_config())['fields']
    for case in data['cases']:
        definitions = case.get('problem_definition', {})
        missing = [f for f in fields if not definitions.get(f, {}).get('value_text')]
        hard = [f for f in missing if f in hard_fields and not (definitions.get(f, {}).get('reason_source') == 'explicit_gap'
            and (definitions.get(f, {}).get('reason') or '').strip())]
        labels = [f + ('（硬阻塞）' if f in hard else '') for f in missing]
        lines.append(f"- {case['case_id']} 问题定义完成度：{len(fields)-len(missing)}/{len(fields)} 字段有证据；缺失：{', '.join(labels) or '无'}")
        if hard:
            lines.append(f"- 硬阻塞字段：{', '.join(hard)} 缺失且无 reason，无法进入任何 Track 准入。")
        evidence = data['checkpoint'].get('stop_evidence', {})
        completed_ids = {c['coverage_witness']['case_id'] for c in evidence.get('case_completions', [])}
        if evidence.get('coverage_witness'):
            completed_ids.add(evidence['coverage_witness']['case_id'])
        machine = '机器完成' if stop == 'case_coverage_complete' and case['case_id'] in completed_ids else '机器覆盖未完成'
        lines.append(f"- {case['case_id']}：{machine} / {human_audit_text(case)}。")
    calls = quality.get('model_calls')
    if calls:
        lines.append(f"- 模型调用：本次 invocation {calls['invocation']}；workspace 累计 {calls['workspace']}。")
        for row in calls.get('by_table', []):
            scope = f"{row['case_id']}/{row['table_id']}" if row['table_id'] else '未归属（历史事件缺少范围）'
            lines.append(f"- 调用分布 {scope}：本次 {row['invocation']}；累计 {row['workspace']}。")
    interruptions = [e.get('details', e) for e in data.get('events', []) if e['kind'] == 'round_interrupted']
    if interruptions:
        interruption = interruptions[-1]
        stage = {'semantic': '语义', 'attribution': '归属', 'extraction': '抽取'}.get(interruption.get('pending_stage'), '模型')
        kind = interruption.get('pending_kind')
        if kind == 'next_stage_blocked_by_budget':
            lines.append(f'- 最近中断记录：下一{stage}调用被预算阻止；不是已发调用无响应。')
        elif kind == 'contract_rejected':
            lines.append('- 最近中断记录：模型输出契约拒绝；不是预算阻止或调用无响应。')
        elif kind == 'awaiting_response':
            lines.append(f'- 最近中断记录：{stage}调用尚无响应。')
    citation_quality = quality.get('citation_identity', {})
    if citation_quality.get('status') == 'disabled':
        lines.append('- 引用身份核验：未启用；unknown 不表示服务失败。')
    elif citation_quality:
        lines.append(f"- 引用核验请求：{citation_quality['requests_consumed']}/{citation_quality['max_requests']}；仅核对标识/标题。")
    for source in data['sources']:
        identity = source.get('citation_identity') or {}
        if identity:
            lines.append(f"- 引用身份 {source['source_id']}：{identity.get('state', 'unknown')}；{identity.get('cross_check', '')}；{identity.get('reason', '')}")
    for event in data.get('events', []):
        if event['kind'] == 'assessment_started':
            assessment = event.get('details', event)
            origin = assessment.get('inherited_from') or assessment.get('restart_reason') or '独立表范围'
            cursor_source = assessment.get('cursor_source', 'legacy_unknown')
            lines.append(f"- 分段游标 {assessment.get('case_id', '?')}/{assessment.get('table_id', '?')}："
                         f"{assessment['source_id']} 从第 {assessment['start_segment']} 段开始；"
                         f"cursor_source={cursor_source}；{origin}。")
    diagnostics = quality.get('field_diagnostics', [])
    if diagnostics:
        lines += ['', '### 每字段缺口归因', '', '计数来自已记录观察，原因可并存；共享抽取次数不可跨字段求和。', '']
        for item in diagnostics:
            if item['has_evidence']:
                continue
            lines.append(f"- {item['case_id']}/{item['table_id']}.{item['field']}：{item['attempt_status']} / {item['diagnostic_status']}；{item['reasons']}")
            for source in item['sources']:
                state = '分段已处理，字段无证据' if source['processing_status'] == 'done' else '分段处理尚未确认完成'
                lines.append(f"  来源 {source['source_id']}：{state}；提供分段 {source['provided_segments']} / 总数 {source['total_segments']}；"
                             f"上下文尝试 {source['context_presentations']}，共享抽取 {source['shared_extraction_calls']}，"
                             f"字符串通过候选 {source['grounded_candidates']}，归属记录 {source['attribution_records']}，语义记录 {source['semantic_records']}；{source['reasons']}")
    attribution = quality.get('attribution')
    if attribution:
        precision = attribution['attribution_precision']
        lines += [f"- 归属验证：attributed {attribution['attributed']}；abstained {attribution['abstained']}；absent {attribution['absent']}；pending_attribution {attribution['pending_attribution']}",
                  f"- 双复核通过候选：{attribution['eligible_supported']}；人工已抽查 {attribution['audited_samples']}（正确 {attribution['audited_correct']}，错误 {attribution['audited_incorrect']}）",
                  f"- 抽查归属精确率：{pct(precision) if precision is not None else 'unknown'}；抽查覆盖率 {pct(attribution['audit_coverage'])}；仅描述已抽查样本，未抽查不计为正确。"]
        if 'same_model_used' in attribution:
            lines.append(f"- 双审模型：{', '.join(attribution.get('review_models', [])) or 'unknown'}；"
                         f"same_model_used={attribution['same_model_used']}；绑定记录对数 {attribution.get('model_pairs_recorded', 0)}；"
                         "包括被拒绝的复核对；不同请求/reviewer ID 不保证误差独立。")
    lines += ["- 搜索边界：有限运行范围，仅反映当前配置、端点与查询策略；未声称全局搜索空间耗尽。",
              "- 能力边界：接地与流程校验不保证语义判断或反证充分性；人工审计状态仅描述已记录抽查。",
              f"- 配置上限：发现 {limit if limit is not None else 'N/A'}；正文分析 {counts.get('analysis_limit', 'N/A')}；纳入案例 {counts.get('accepted_limit', 'N/A')}。"]
    if stop == LEGACY_STOP:
        lines += ["- 历史停止声明未通过现行守卫；本视图仅供审计，不改写原始批次。"]
    stop_evidence = data["checkpoint"].get("stop_evidence") or {}
    if stop_evidence.get("budget_cause"):
        lines.append("- 预算停止：" + stop_evidence["budget_cause"])
        usage = stop_evidence.get("calls_by_category_at_exhaustion", {})
        lines.append("- 耗尽时调用分布：" + (", ".join(f"{k}={v}" for k, v in usage.items()) or "无模型调用"))
    if stop_evidence.get("case_audit"):
        audit = stop_evidence["case_audit"]
        lines.append(f"- 停止时覆盖链人工审计（历史快照）：{audit['audited_samples']}/{audit['eligible_supported']}；最低样本 {audit['required_audit_samples']}")
    if stop_evidence.get("rationale"):
        lines.append("- 停止说明：" + stop_evidence["rationale"])
    for endpoint in stop_evidence.get("endpoints", []):
        lines.append(f"- 端点 `{endpoint['id']}`：实际 {endpoint['pages_fetched']} 页；{endpoint['limitation']}")
    failures = data.get("grounding_failures", [])
    if "grounding_failures" in data:
        lines.append(f"- 源接地失败记录：{len(failures)}；字符串匹配不代表语义支持已验证。")
    else:
        lines.append("- 源接地检查：未提供验证记录，不能视为已通过。")
    for failure in failures:
        lines.append(f"  - {failure.get('case_id', '—')}/{failure.get('field', '—')}：{failure.get('failure_type', 'unknown')}（{failure.get('source_id', '—')}）")
    if good: lines += ["", "关键发现："+"；".join(c.get("scenario_description",c["case_id"]) for c in good)]
    lines += ["","## 二、案例清单","","### 纳入案例","","| Case | Track | 分数 | 场景 | 详情 |","|---|---|---:|---|---|"]
    for case in good:
        for track in accepted_tracks(case, data.get("config_snapshot")):
            link=f"[打开](cases/{case['case_id']}.md)"
            lines.append(f"| `{case['case_id']}` | `{track}` | {score_text(case['tracks'][track].get('score_normalized'))} | {case.get('scenario_description','')} | {link} |")
    if not good: lines.append("| — | — | — | 无 | — |")
    for case in good:
        pd=case.get("problem_definition", {})
        lines += ["", f"#### `{case['case_id']}` 定义摘要", ""]
        for label, key in [("现实问题","real_world_problem"),("参与方","parties_and_roles"),("量子机制","quantum_mechanism_role"),("约束","constraints"),("部署边界","deployment_boundary")]:
            field = pd.get(key, {}) or {}
            value = field.get("value_text") or (field.get("reason") if field.get('reason_source') == 'explicit_gap' else None) or "未记录显式缺失原因"
            lines.append(f"- **{label}**：{value}")
        lines += ["", f"→ [完整定义](cases/{case['case_id']}.md)"]
    lines += ["","### 未纳入或 Track 失败","","| Case | Track | 原因 |","|---|---|---|"]
    failures=0
    for case in data["cases"]:
        for track,evaluation in case.get("tracks",{}).items():
            if track not in accepted_tracks(case, data.get("config_snapshot")): lines.append(f"| `{case['case_id']}` | `{track}` | {failure_context(evaluation, (data.get("config_snapshot") or {}).get("tracks", {}).get(track, {}).get("min_total_score", 15))} |"); failures+=1
    if not failures: lines.append("| — | — | 无 |")
    lines += ["","## 三、来源使用情况","",f"- 有实质证据的来源：{len(evidence_sources)} / {len(data['sources'])}",f"- 仅标题/元数据级来源：{sum(1 for s in data['sources'] if s.get('status')=='opened_metadata_only')}","","| Source | 状态 | 支持案例 | 证据摘录 |","|---|---|---|---|"]
    for source in evidence_sources:
        evidence_text = str(len(source.get("evidence", []))) + "项完整证据（见逐项原文证据）"
        if not evidence_text:
            evidence_text = "字段级/准入证据引用"
        lines.append(f"| `{source['source_id']}` | `{source.get('status')}` | {', '.join(source.get('supports_cases',[])) or '—'} | {evidence_text} |")
    if not evidence_sources: lines.append("| — | — | — | 无 |")
    discovered_layers = {}
    for event in data.get("events", []):
        if event.get("kind") == "source_discovered":
            layer = (event.get("details") or {}).get("layer", "unknown")
            discovered_layers[layer] = discovered_layers.get(layer, 0) + 1
    lines += ["", "### 发现层级分布", "", "| Layer | 发现数 |", "|---|---:|"]
    lines += [f"| `{layer}` | {count} |" for layer, count in sorted(discovered_layers.items())]
    if quality_warnings:
        lines.append("- ⚠️ " + "；".join(format_warning(w) for w in quality_warnings))
    lines += ["","## 四、查询执行","",f"- 种子：完成 {len(progress.get('seed_completed',[]))}，不适用 {len(progress.get('seed_not_applicable',[]))}，超出范围执行 {len(progress.get('seed_executed_outside_scope',[]))}，待完成 {len(progress.get('seed_pending',[]))}",f"- 自适应：{len(progress.get('adaptive_queries',[]))} 条，产生新来源 {sum(q.get('produced_new_sources') or 0 for q in progress.get('adaptive_queries',[]))} 条",f"- 收敛：`{progress.get('adaptive_converged',False)}`；循环：`{progress.get('loop_status','unknown')}`"]
    queries=progress.get('adaptive_queries',[]); keys=[q.get('keyword_or_source') for q in queries]
    if len(keys)!=len(set(keys)): lines.append("- ⚠️ 自适应查询存在重复 keyword_or_source")
    if progress.get('adaptive_converged') and not any((q.get('hits') or 0)>0 for q in queries): lines.append("- ⚠️ 收敛声明缺少非零 hits 证据")
    if not good:
        trail_status = "无纳入案例"
    elif all(discovery_trail(case).get("discovered_via") for case in good):
        trail_status = "完整"
    else:
        trail_status = "部分为空（事件未关联）"
    case_files = [f"`cases/{case['case_id']}.md`" for case in data.get("cases", [])]
    checkpoint_events = [event for event in data.get("events", []) if event.get("kind") == "checkpoint"]
    batch_size = counts.get("batch_size", "N/A")
    lines += ["","## 五、质量指标","",f"- Primary evidence ratio：{pct(quality.get('primary_evidence_ratio'))}",f"- Insufficient-evidence admission ratio：{pct(quality.get('insufficient_evidence_admission_ratio'))}",f"- Quantitative quote coverage：{pct(quality.get('quantitative_quote_coverage'))}","- 警告："+("；".join(format_warning(w) for w in quality.get('warnings',[])) or "无"),"","## 六、审计提示","",f"- 发现轨迹完整性：{trail_status}",f"- 事件记录：{len(data.get('events',[]))}",f"- Checkpoint 次数：{len(checkpoint_events)}",f"- Checkpoint 间隔（成功打开来源数）：{batch_size}",f"- 发现池与打开来源相等：{'是（run 结束时可正常；请查看中间 checkpoint 的 sources_unattempted）' if pool==counts.get('opened_sources') else '否'}","","## 七、附件","",f"- 批次 JSON：`{data['run_id']}/calibration/batch.json`",f"- Checkpoint：`{data['run_id']}/checkpoints/{data['batch_id']}.json`",f"- 单案例草稿：{('、'.join(case_files)) if case_files else '无'}"]
    if attribution and 'required_audit_samples' in attribution:
        lines += [f"- 最低审计覆盖率 {attribution['min_audit_coverage']:.1%}；本批最低样本 {attribution['required_audit_samples']}"]
        if attribution.get('audit_warning'):
            lines += ['⚠️ ' + attribution['audit_warning']]
    if quality.get('cost_breakdown'):
        lines += ['', '## 模型成本分解', '', '| 环节 | 调用 | 响应 | 输入 token（已知） | 输出 token（已知） | usage 未知调用 | USD |',
                  '|---|---:|---:|---:|---:|---:|---:|']
        for category, row in quality['cost_breakdown'].items():
            usd = f"{row['usd']:.6f}" if row['usd'] is not None else 'unknown'
            def tokens(key):
                known = row['known_token_calls'][key]
                return str(row[key]) if known == row['calls'] else f"{row[key]} (partial)" if known else 'unknown'
            lines += [f"| {category} | {row['calls']} | {row['responses']} | {tokens('input_tokens')} | {tokens('output_tokens')} | {row['unknown_usage_calls']} | {usd} |"]
        lines += ['', '缺失 usage/价格不按零成本处理；USD 仅采信调用回执，不推测网关计价。']
    lines += ['', '## 八、逐项原文证据', '', '原生评审记录不等于人工确认；缺证及未完成状态保持不变。']
    source_index = {source['source_id']: source for source in data.get('sources', [])}
    for case in data.get('cases', []):
        lines += ['', '## ' + case['case_id']] + render_case_evidence(case, source_index, data.get("grounding_failures", []))
    return "\n".join(lines)+"\n"

def render_case_files(data, output_dir):
    output_dir = Path(output_dir)
    source_index = {s.get("source_id"): s for s in data.get("sources", [])}
    output_dir.mkdir(parents=True, exist_ok=True)
    for case in data.get("cases", []):
        lines = [
            f"# {case['case_id']} [CALIBRATION DRAFT]",
            "",
            "> 本文件由 batch JSON 自动生成，仅供校准复盘；事实源仍是同批次 JSON。",
            "> 有限运行范围；不做全局证据穷尽宣称，接地与流程校验不保证语义判断或反证充分性。",
            "",
            f"- 批次停止：`{data.get('stop_reason')}`；状态：{data.get('run_status')}",
            f"- 人工审计：{human_audit_text(case)}。",
            "",
            "## 摘要",
            "",
            case.get("scenario_description", ""),
            "",
            "## 问题定义",
            "",
            "| 字段 | 内容 | 证据 |",
            "|---|---|---|",
        ]
        for name, field in case.get("problem_definition", {}).items():
            value = field.get("value_text") or ("缺失：" + ((field.get("reason") if field.get('reason_source') == 'explicit_gap' else None) or "未记录显式缺失原因"))
            evidence = (
                f"{field.get('source_id', '')}；{field.get('location', '')}（见下方完整证据）"
                if field.get("quote") else "—"
            )
            lines.append(f"| `{name}` | {value} | {evidence} |")
        lines += [
            "",
            "## Track 结果",
            "",
            "| Track | 准入 | 归一化分数 | 失败原因 |",
            "|---|---|---:|---|",
        ]
        for track, evaluation in case.get("tracks", {}).items():
            admission = "✅ 通过" if admission_is_passed(evaluation.get("passed_admission")) else "未通过"
            lines.append(
                f"| `{track}` | {admission} | {score_text(evaluation.get('score_normalized'))} | "
                f"{failure_context(evaluation, (data.get("config_snapshot") or {}).get("tracks", {}).get(track, {}).get("min_total_score", 15))} |"
            )
            if evaluation.get('scores'):
                lines += [
                    "",
                    f"### `{track}` 评分维度",
                    "",
                    "| 维度 | 分数 |",
                    "|---|---:|",
                ]
                lines += [
                    f"| `{key}` | {score_text(value)} |"
                    for key, value in evaluation["scores"].items()
                ]
        lines += ["", "## 证据来源", ""]
        for source_id in case.get("source_ids", []):
            source = source_index.get(source_id, {})
            role = classify_source_role(case, source_id)
            lines.append(f"- **{role}**：`{source_id}`")
            lines += [
                f"  - 位置：{evidence.get('location', '')}（见逐项完整证据）"
                for evidence in source.get("evidence", [])
            ]
        if not case.get("source_ids"):
            lines.append("- 未关联来源")
        lines += ['', '## 逐项完整证据', ''] + render_case_evidence(case, source_index, data.get("grounding_failures", []))
        trail = discovery_trail(case)
        lines += [
            "",
            "## 搜索轨迹",
            "",
            f"- Run：`{data.get('run_id', '')}`",
            f"- Batch：`{data.get('batch_id', '')}`",
            f"- 发现查询：{trail.get('discovered_via') or '未记录'}",
            f"- 说明：{trail.get('event_note', '—')}",
        ]
        (output_dir / f"{case['case_id']}.md").write_text("\n".join(lines) + "\n")

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('batch_json', type=Path)
    ap.add_argument('output_md', type=Path)
    ap.add_argument('--cases-dir', type=Path)
    ap.add_argument('--legacy-audit', action='store_true', help='仅审计历史 discovery_pool_exhausted，不认可原完成声明')
    args = ap.parse_args()
    data = json.loads(args.batch_json.read_text())
    result = render(data, legacy_audit=args.legacy_audit)
    args.output_md.write_text(result)
    render_case_files(data, args.cases_dir or args.batch_json.parent / 'cases')

if __name__ == '__main__':
    main()
