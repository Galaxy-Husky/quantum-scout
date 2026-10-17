"""Batch structure, evaluation and stop contract validation; no rendering."""

CHECKPOINT_DELTA_KEYS = ("opened_sources", "attempted_sources", "extracted_candidate_cases",
                         "problem_definition_complete_cases", "accepted_cases", "cache_hits")


def criterion_is_true(value):
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def admission_is_passed(value):
    if value is True or value == 1 or (isinstance(value, str) and value.strip().lower() in {"true", "1"}):
        return True
    if value is False or value == 0 or (isinstance(value, str) and value.strip().lower() in {"false", "0"}):
        return False
    raise ValueError("invalid passed_admission: " + repr(value))


WARNING_CATEGORIES={"audit_coverage","citation_unverified","cross_check_partial","cross_check_conflict","search_adequacy","source_level","checkpoint_delta","trace_consistency","evidence_breakdown","grounding"}


def warning(category, message):
    if category not in WARNING_CATEGORIES:
        raise ValueError("unknown warning category: " + category)
    return {"category":category,"message":message}


def validate_admission_consistency(data):
    for case in data.get("cases", []):
        for track, evaluation in case.get("tracks", {}).items():
            criteria=evaluation.get("criteria")
            if not isinstance(criteria,dict) or not criteria:
                raise ValueError(f"missing admission criteria for {case.get('case_id')}/{track}")
            expected=all(criterion_is_true(v) for v in criteria.values())
            if admission_is_passed(evaluation.get("passed_admission")) != expected:
                raise ValueError(f"admission/criteria mismatch for {case.get('case_id')}/{track}")


def validate_structure(data):
    required={"run_id","batch_id","run_status","stop_reason","counts","quality","sources","cases","events","checkpoint"}
    missing=sorted(required-set(data))
    if missing: raise ValueError("missing required batch JSON keys: "+", ".join(missing))
    if data.get("run_status") not in {"preparing","running","completed","incomplete"}:
        raise ValueError("invalid run_status: "+repr(data.get("run_status")))
    quality_warnings=data.get("quality",{}).get("warnings")
    if not isinstance(quality_warnings,list) or any(not isinstance(w,dict) or w.get("category") not in WARNING_CATEGORIES or not w.get("message") for w in quality_warnings):
        raise ValueError("quality.warnings 必须是带封闭 category 的对象数组")
    policy = data.get('quality', {}).get('limit_policy')
    if policy and policy.get('owner') == 'online.config':
        effective = policy['effective']
        expected = {'analysis_limit': effective['analysis_limit'], 'accepted_limit': effective['max_cases'],
                    'batch_size': effective['batch_size'], 'discovery_limit': effective['discovery_limit'],
                    'diminishing_returns_threshold': effective['stall_rounds']}
        if policy.get('phase_applied') is not False or any(data['counts'].get(k) != v for k, v in expected.items()):
            raise ValueError('Online counts disagree with effective online limit policy')
    for event in data.get("events",[]):
        kind=event.get("kind"); details=event.get("details") or {}
        if kind=="source_discovered":
            if details.get("layer") not in {"layer1","layer2","layer3","adaptive"}:
                raise ValueError("source_discovered details.layer 无效")
            if not details.get("query_id") or "position" not in details:
                raise ValueError("source_discovered 缺少 query_id 或 position")
        if kind=="source_opened" and details.get("access_level")!="full_text":
            raise ValueError("source_opened 必须使用 full_text")
        if kind=="opened_metadata_only" and details.get("access_level")!="metadata_only":
            raise ValueError("opened_metadata_only 必须使用 metadata_only")
    sources={s.get("source_id"):s for s in data["sources"]}
    if None in sources or "" in sources or len(sources) != len(data["sources"]):
        raise ValueError("来源 ID 缺失或重复")
    failures = data.get("grounding_failures", [])
    failure_types = {"citation_mismatch", "quote_not_found", "semantic_mismatch", "source_not_opened_in_run", "source_mismatch", "source_text_unavailable", "invalid_evidence", "counter_evidence_invalid"}
    if not isinstance(failures, list) or any(not isinstance(f, dict) or f.get("failure_type") not in failure_types or not all(k in f for k in ("case_id", "field", "source_id")) for f in failures):
        raise ValueError("grounding_failures 必须保留失败类型、案例、字段和来源标识")
    opened=sum(s.get("status")=="opened" for s in sources.values())
    metadata=sum(s.get("status")=="opened_metadata_only" for s in sources.values())
    counts=data["counts"]
    if counts.get("opened_sources")!=opened or counts.get("opened_metadata_only")!=metadata:
        raise ValueError("来源状态与 counts 不一致")
    if counts.get("sources_unattempted") != counts.get("discovery_sources",0)-counts.get("attempted_sources",0):
        raise ValueError("sources_unattempted 计算错误")
    cp=data["checkpoint"]
    ids=cp.get("new_source_ids"); input_ids=cp.get("input_source_ids"); opened_since=cp.get("opened_since_last_checkpoint")
    if not isinstance(ids,list) or ids!=input_ids or len(ids)!=opened_since:
        raise ValueError("checkpoint 增量来源字段不一致")
    delta=cp.get("counts_delta")
    if not isinstance(delta,dict) or any(not isinstance(delta.get(k),int) for k in CHECKPOINT_DELTA_KEYS):
        raise ValueError("checkpoint counts_delta 不完整")
    batch_size=counts.get("batch_size")
    if not isinstance(batch_size,int) or batch_size<=0: raise ValueError("batch_size 必须为正整数")
    cp_events=[e for e in data["events"] if e.get("kind")=="checkpoint"]
    for index, event in enumerate(cp_events):
        n=(event.get("details") or {}).get("opened_since_last_checkpoint")
        details = event.get("details") or {}
        final = details.get("final") is True or details.get("completed") is True
        if type(n) is not int or not 0 <= n <= batch_size: raise ValueError("checkpoint 事件 opened_since_last_checkpoint 无效")
        if final and (index != len(cp_events) - 1 or data["run_status"] not in {"completed", "incomplete"}):
            raise ValueError("最终 checkpoint 只能对应本 run 的终止恢复点")
        if not final and n != batch_size: raise ValueError("普通 checkpoint 间隔错误")


def validate_adaptive_queries(data):
    progress=data["checkpoint"]["search_progress"]; queries=progress["adaptive_queries"]
    ids=[q.get("id") for q in queries]; event_ids=[(e.get("details") or {}).get("id") for e in data["events"] if e.get("kind")=="adaptive_query"]
    if any(not x for x in ids) or len(ids)!=len(set(ids)) or event_ids!=ids:
        raise ValueError("adaptive 查询与事件轨迹不一致")
    index={(e.get("details") or {}).get("id"): i for i,e in enumerate(data["events"]) if e.get("kind")=="adaptive_query"}
    seen=set(); actual={q:set() for q in ids}
    for i,e in enumerate(data["events"]):
        if e.get("kind")!="source_discovered": continue
        q=(e.get("details") or {}).get("query_id"); sid=e.get("source_id")
        if q and q.startswith("ADAPT-"):
            if q not in index or i<=index[q]: raise ValueError(f"{q} 的发现事件因果顺序错误")
            if sid and sid not in seen: actual[q].add(sid)
        if sid: seen.add(sid)
    for q in queries:
        n=q.get("produced_new_sources")
        if type(n) is not int or n<0 or n!=len(actual[q["id"]]):
            raise ValueError(f"{q.get('id')} produced_new_sources 与事件不一致")


SUCCESS_STOPS = {"analysis_limit_reached", "max_cases_reached", "case_coverage_complete"}


INCOMPLETE_STOPS = {"diminishing_returns", "operational_pool_exhausted", "user_aborted", "error", "budget_exhausted"}


LEGACY_STOP = "discovery_pool_exhausted"


def validate_search_adequacy(data, legacy_audit=False):
    """Endpoint coverage describes operations, never global literature exhaustion."""
    judgement = data["checkpoint"]["discovery_judgement"].get("judgement")
    if judgement == LEGACY_STOP and legacy_audit and data["stop_reason"] == LEGACY_STOP:
        return
    if judgement != "not_exhausted":
        raise ValueError("discovery_judgement 必须为 not_exhausted；旧耗尽声明只允许 --legacy-audit 阅读")


def validate_operational_stop(data):
    cp = data["checkpoint"]
    progress = cp["search_progress"]
    evidence = cp.get("stop_evidence") or {}
    if not evidence.get("rationale"):
        raise ValueError("操作性停止缺 stop_evidence.rationale")
    if data["counts"]["sources_unattempted"] != 0:
        raise ValueError("操作性停止仍有未尝试来源；先尝试并记录阻断原因")
    if data["stop_reason"] == "diminishing_returns":
        threshold = data["counts"].get("diminishing_returns_threshold")
        if type(threshold) is not int or threshold <= 0:
            raise ValueError("缺少配置快照 diminishing_returns_threshold 正整数")
        queries = progress["adaptive_queries"]
        tail = queries[-threshold:]
        if (progress.get("seed_pending") or len(tail) != threshold
                or any(q.get("status") != "completed" or q.get("produced_new_sources") != 0 for q in tail)
                or any(not q.get("keyword_or_source") for q in tail)
                or len({q["keyword_or_source"].strip().casefold() for q in tail}) != threshold
                or evidence.get("basis") != "new_sources"
                or evidence.get("window_query_ids") != [q["id"] for q in tail]):
            raise ValueError("diminishing_returns 必须对应末 N 条不同、成功执行且无新来源的查询")
        return
    actions = evidence.get("actions")
    endpoints = evidence.get("endpoints")
    if not isinstance(actions, list) or not actions or not isinstance(endpoints, list) or not endpoints:
        raise ValueError("operational_pool_exhausted 缺 actions 或 endpoints 清单")
    action_ids = [a.get("id") for a in actions]
    if any(not x for x in action_ids) or len(set(action_ids)) != len(action_ids):
        raise ValueError("操作清单 ID 缺失或重复")
    for action in actions:
        if action.get("status") not in {"completed", "failed", "blocked"} or not action.get("reason"):
            raise ValueError("每个操作须有终态和原因；仍可执行的任务不得提前停止")
    pending = {q if isinstance(q, str) else q["id"] for q in progress.get("seed_pending", [])}
    blocked = {a["id"] for a in actions if a["status"] in {"failed", "blocked"}}
    if not pending <= blocked:
        raise ValueError("尚未执行的种子缺少失败/阻断记录")
    for endpoint in endpoints:
        if (not endpoint.get("id") or type(endpoint.get("pages_fetched")) is not int
                or endpoint["pages_fetched"] < 0 or not endpoint.get("limitation")):
            raise ValueError("端点记录须有 id、实际页数、能力或配置限制")
    if len({e["id"] for e in endpoints}) != len(endpoints):
        raise ValueError("端点 ID 重复")


def validate_completion_guard(data, legacy_audit=False):
    c = data["counts"]
    stop = data["stop_reason"]
    cp = data["checkpoint"]
    status = data["run_status"]
    if cp.get("run_status") != status or cp.get("stop_reason") != stop:
        raise ValueError("checkpoint 与批次 run_status/stop_reason 不一致")
    if stop == LEGACY_STOP:
        if not legacy_audit:
            raise ValueError("discovery_pool_exhausted 已废弃；旧批次使用 --legacy-audit 审计，不能据此声明完整结束")
        return
    if stop == "evidence_coverage_sufficient":
        raise ValueError("语义 verifier 尚未接入；不得声明 evidence_coverage_sufficient")
    if status in {"preparing", "running"}:
        if stop is not None or cp.get("completed") is not False:
            raise ValueError("进行中的 run 必须 stop_reason=null、checkpoint.completed=false")
        return
    if stop not in SUCCESS_STOPS | INCOMPLETE_STOPS:
        raise ValueError("未知 stop_reason: " + repr(stop))
    expected = "completed" if stop in SUCCESS_STOPS else "incomplete"
    if status != expected or cp.get("completed") is not (expected == "completed"):
        raise ValueError("停止原因与 run_status/checkpoint.completed 不一致")
    if stop == "analysis_limit_reached":
        opened = {e.get("source_id") for e in data["events"] if e.get("kind") == "source_opened" and (e.get("details") or {}).get("access_level") == "full_text"}
        if type(c["analysis_limit"]) is not int or c["analysis_limit"] <= 0 or c["opened_sources"] < c["analysis_limit"] or opened != {s["source_id"] for s in data["sources"] if s.get("status") == "opened"}:
            raise ValueError("analysis_limit_reached 计数或轨迹不满足")
    elif stop == "max_cases_reached":
        # accepted_cases is cumulative; earlier accepted IDs must be explicit.
        current = {case["case_id"] for case in accepted_cases(data)}
        previous = set(data.get("previous_accepted_case_ids", []))
        if (type(c["accepted_limit"]) is not int or c["accepted_limit"] <= 0
                or c["accepted_cases"] != len(current | previous)
                or c["accepted_cases"] < c["accepted_limit"]):
            raise ValueError("max_cases_reached 纳入案例计数不满足")
    elif stop == "case_coverage_complete":
        from coverage_policy import validate_case_coverage_stop
        validate_case_coverage_stop(data)
    elif stop == "budget_exhausted":
        if not cp.get("stop_evidence", {}).get("budget_cause"):
            raise ValueError("budget_exhausted requires the actual online budget cause")
    elif stop in {"diminishing_returns", "operational_pool_exhausted"}:
        validate_operational_stop(data)


def evidence_breakdown_warnings(data):
    ratio=(data.get("quality") or {}).get("insufficient_evidence_admission_ratio")
    if isinstance(ratio,(int,float)) and ratio>0 and not (data.get("quality") or {}).get("insufficient_evidence_breakdown"):
        return [warning("evidence_breakdown","insufficient_evidence_admission_ratio > 0 但缺少 breakdown")]
    return []


def accepted_tracks(case, config=None):
    return [track for track, evaluation in case.get("tracks", {}).items()
            if admission_is_passed(evaluation.get("passed_admission")) and (evaluation.get("score_normalized") or 0) >=
            (config or {}).get("tracks", {}).get(track, {}).get("min_total_score", 15)]


def accepted_cases(data):
    return [case for case in data.get("cases", []) if accepted_tracks(case, data.get("config_snapshot"))]

