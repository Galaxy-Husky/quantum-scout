-- 1. 低延迟量子协调筛选（内部审查）：不展示对外名称。
SELECT c.case_id, c.domain, c.sub_domain,
       c.max_latency_ns / 1e6 AS max_latency_ms,
       ct.score_normalized
FROM cases c JOIN case_tracks ct USING(case_id)
WHERE c.human_audit_status != 'rejected' AND ct.track_id = 'nonlocal-coordination'
  AND ct.passed_admission = 1
  AND ct.score_normalized >= 15
  AND c.max_latency_ns < 100 * 1e6
ORDER BY ct.score_normalized DESC;

-- 2. 严格满足成本小于100万美元且5年内可部署，不将未知值当满足。
SELECT c.case_id, c.domain, c.cost_usd_max,
       c.deployment_years_max, ct.track_id, ct.score_normalized
FROM cases c JOIN case_tracks ct USING(case_id)
WHERE c.human_audit_status != 'rejected' AND ct.passed_admission = 1
  AND ct.score_normalized >= 15
  AND c.cost_usd_max < 1e6
  AND c.deployment_years_max <= 5
ORDER BY ct.score_normalized DESC;
-- 若用户要求“保留未知候选”，另行使用 IS NULL OR，并明确标注未验证。

-- 3. 同时通过两条 Track 的案例。
SELECT c.case_id, c.domain,
       a.score_normalized AS score_coordination,
       b.score_normalized AS score_security
FROM cases c
JOIN case_tracks a ON c.case_id = a.case_id
  AND a.track_id = 'nonlocal-coordination'
JOIN case_tracks b ON c.case_id = b.case_id
  AND b.track_id = 'quantum-security'
WHERE c.human_audit_status != 'rejected' AND a.passed_admission = 1 AND a.score_normalized >= 15
  AND b.passed_admission = 1 AND b.score_normalized >= 15;

-- 4. 案例总数与各 Track 数量。
SELECT COUNT(DISTINCT case_id) AS unique_cases FROM cases WHERE human_audit_status != 'rejected';
SELECT track_id, COUNT(*) AS admitted_cases
FROM case_tracks JOIN cases USING(case_id)
WHERE human_audit_status != 'rejected' AND passed_admission = 1 AND score_normalized >= 15
GROUP BY track_id;
-- Track 总和可超过唯一案例数；失败评估行不算 Track 归属。

-- 5. 客户查询：低延迟量子协调案例，用对外名称展示。
SELECT c.case_id, c.display_name_zh, c.domain,
       c.max_latency_ns / 1e6 AS max_latency_ms,
       ct.score_normalized
FROM cases c
JOIN case_tracks ct ON c.case_id = ct.case_id
WHERE c.human_audit_status != 'rejected' AND ct.track_id = 'nonlocal-coordination'
  AND ct.passed_admission = 1
  AND ct.score_normalized >= 15
  AND c.max_latency_ns IS NOT NULL
  AND c.max_latency_ns < 100 * 1e6
ORDER BY ct.score_normalized DESC;

-- 6. 仅查询问题定义完整且已进入生产部署的案例。
SELECT case_id, domain, deployment_stage
FROM cases
WHERE human_audit_status != 'rejected' AND problem_definition_complete = 1
  AND deployment_stage = 'production';

-- 7. 查找问题定义中 real_world_problem 字段有完整证据的案例。
SELECT c.case_id, c.domain, cpd.value_text
FROM cases c
JOIN case_problem_definitions cpd ON c.case_id = cpd.case_id
WHERE c.human_audit_status != 'rejected' AND cpd.field = 'real_world_problem'
  AND cpd.value_text IS NOT NULL;


-- 8. 孤儿评估记录检查：仅在事务提交后运行；写入中途运行会因评估先写而误报。任何输出都表示数据不一致。
SELECT DISTINCT ce.case_id, ce.track_id
FROM case_evaluations ce
LEFT JOIN case_tracks ct
  ON ce.case_id = ct.case_id AND ce.track_id = ct.track_id
WHERE ct.case_id IS NULL;

-- 9. 列出问题定义不完整的案例及缺失字段。
SELECT c.case_id, c.domain,
       GROUP_CONCAT(cpd.field) AS missing_fields
FROM cases c
LEFT JOIN case_problem_definitions cpd
  ON c.case_id = cpd.case_id AND cpd.value_text IS NULL
WHERE c.problem_definition_complete = 0
GROUP BY c.case_id, c.domain;


-- 10. 历史声明审计（语义见 ../CHANGELOG.md），不作为当前停止依据。
SELECT log_id,
       json_extract(details_json, '$.discovery_judgement.judgement') AS judgement,
       json_array_length(json_extract(details_json, '$.discovery_judgement.evidence.layer1_sources_executed')) AS n_l1,
       json_array_length(json_extract(details_json, '$.discovery_judgement.evidence.layer2_queries_executed')) AS n_l2,
       json_array_length(json_extract(details_json, '$.discovery_judgement.evidence.layer3_queries_executed')) AS n_l3,
       json_array_length(json_extract(details_json, '$.discovery_judgement.evidence.pagination_completed')) AS n_pages,
       json_extract(details_json, '$.discovery_judgement.evidence.discovered_after_dedup') AS discovered_after_dedup,
       json_extract(details_json, '$.discovery_judgement.evidence.unopened_remaining') AS unopened_remaining
FROM search_log
WHERE result = 'checkpoint'
  AND json_extract(details_json, '$.discovery_judgement.judgement') = 'discovery_pool_exhausted';

-- 当前人工审计筛选（派生列须与原始抽查同步）；审计/缺项诊断查询刻意保留 rejected。
SELECT case_id, domain FROM cases WHERE human_audit_status = 'verified';
-- 抽查队列；是否机器覆盖完成另查对应批次 stop_reason，标签本身不表示机器完成。
SELECT case_id, domain FROM cases WHERE human_audit_status IN ('unverified', 'partial');
