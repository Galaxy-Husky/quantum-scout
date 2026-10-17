# Calibration batch JSON schema

> 本文件唯一维护：批次 JSON 字段、停止枚举及其状态/举证契约。跨职责规则通过链接引用其权威文档。

`calibration/<batch_id>.json` 是校准审计导出，字段与一致性约束见下文；状态所有权见[执行流程](workflow.md#状态导出与兼容)。生成器必须提供以下顶层键：`run_id`、`batch_id`、`run_status`、`stop_reason`、`counts`、`quality`、`sources`、`cases`、`events`、`checkpoint`。`run_status` 只能是 `preparing`、`running`、`completed` 或 `incomplete`；创建 run 时为 `preparing`，开始搜索或评估后为 `running`，正文/案例上限或全部配置案例覆盖完成时为 `completed`，操作性停止、用户中断或错误时为 `incomplete`。

`counts` 至少包含整数：`discovery_sources`、`discovery_pool_size`、`attempted_sources`、`opened_sources`、`opened_metadata_only`、`sources_unattempted`、`extracted_candidate_cases`、`problem_definition_complete_cases`、`unique_cases`、`accepted_cases`、`cache_hits`、`analysis_limit`、`accepted_limit`、`batch_size`。`discovery_limit` 为实际配置的正整数上限；没有独立发现预算的在线运行必须为 `null`（饱和度 N/A），不得用实际发现数冒充上限。收益递减停止必须复制实际执行阈值：agent 按 phase 执行时取当前 phase 的 `diminishing_returns_threshold`；在线 runner 取在线 JSON 的 `stall_rounds`，不自动继承 phase。在线 `quality.limit_policy` 同时保存 effective 值与未应用的 phase_reference，counts 必须与 effective 一致。分页/命中阈值只作检索诊断，不作为耗尽证据。`opened_sources` 只统计实际读取正文的来源；`opened_metadata_only` 统计只读取标题、摘要、索引或元数据的来源，两者不能互相替代。

`quality` 至少包含 `primary_evidence_ratio`、`insufficient_evidence_admission_ratio`、`quantitative_quote_coverage`（数值或 null）和 `warnings`（对象数组）。每个 warning 必须是 `{category,message}`；category 只允许 `search_adequacy`、`source_level`、`checkpoint_delta`、`trace_consistency`、`evidence_breakdown`、`grounding`、`audit_coverage`、`citation_unverified`、`cross_check_partial`、`cross_check_conflict`。当 `insufficient_evidence_admission_ratio > 0` 时，pilot 复盘必须补充 `insufficient_evidence_breakdown`，按 `metadata_only`、`missing_in_document`、`semantic_ambiguity` 三类记录计数及比例；该 breakdown 只用于归因，不得改变准入或评分规则。

每个 `sources` 元素包含 `source_id`、`status`、`document_version`（字符串或 null）、`error`（字符串或 null）、`evidence`（对象数组；每项的 `quote` 为字符串）和 `supports_cases`（案例 ID 数组）。来源状态使用 `opened`、`opened_metadata_only`、`open_failed`、`excluded` 或 `cache_hit`。`opened` 必须对应实际读取的 PDF/HTML 正文；`opened_metadata_only` 必须在 `document_version` 或对应事件中明确标注 `abstract only`、`metadata/index only` 等范围。`opened_metadata_only` 来源不得出现在任何问题定义、准入、评分或案例证据引用中。

每个 `cases` 元素是一个完整的案例对象，包含 `case_id`、`scenario_description`（字符串）、`sub_domain`（字符串或 null，推荐用于同一业务任务的技术子领域）、`failure_class`（字符串或 null，枚举见下文 `failure_class`）、`problem_definition_complete`、`problem_definition`（八字段对象）、`tracks`、`source_ids` 和 `discovery_trail`。`tracks.<track_id>` 至少包含 `criteria`、`passed_admission`、`score_normalized`、`valid_dimension_count` 和 `failure_class`。`criteria` 是该 Track 的全部准入条件结果，值为 `true`、`false` 或 `insufficient_evidence`。未满足八字段前置门时不调度 Track 评估；在线导出仍保留 `tracks` 缺证占位（criteria 为 insufficient_evidence、passed_admission=0、scores 为 null、证据映射为空），不表示已执行评估。

准入一致性约束（生成器和渲染器都必须自检）：若 `criteria` 的所有值均为 `true`，则 `passed_admission` 必须为 1；只要有一个值不是 `true`，则必须为 0。评分证据不足只能令通过准入的 Track 的 `score_normalized` 为 null、`failure_class` 为 `insufficient_evidence`，不得回改 `passed_admission`。违反约束时必须以 `run_status=incomplete`、`stop_reason=error` 停止，不得继续渲染或提交。

`checkpoint` 至少包含 `completed`、`run_status`、`stop_reason`、`input_source_ids`、`new_source_ids`、`counts`、`counts_delta`、`quality`、`discovery_judgement`、`search_progress` 和 `opened_since_last_checkpoint`。checkpoint 文件是增量恢复清单：不得重复保存之前 checkpoint 的完整 `sources`、`cases` 或历史事件；如保存 `events`，只保存自上一个 checkpoint 以来新增的来源处理、候选、评估、查询和 checkpoint 事件。`input_source_ids` 与 `new_source_ids` 都只表示本批自上一个 checkpoint 以来成功读取正文的来源 ID，二者必须相同，长度必须等于 `opened_since_last_checkpoint`，不包含前批 ID，也不包含 `opened_metadata_only`。`counts_delta` 是本批相对前一 checkpoint 的计数变化，至少包含 `opened_sources`、`attempted_sources`、`extracted_candidate_cases`、`problem_definition_complete_cases`、`accepted_cases` 和 `cache_hits`；数值必须为整数，累计 `counts` 仍使用同一时刻的全量计数。`opened_since_last_checkpoint` 是自上一个 checkpoint 以来成功打开的正文来源数；普通 checkpoint 必须等于 `batch_size`，run 结束时的最终 checkpoint 可以小于该值；其事件设 `details.final=true`，普通事件不得设 final。final 仅表示最后一次快照，操作性停止仍为 `completed=false`。`search_progress` 仍保存完整收敛状态；完整来源和案例事实只在最终 `calibration/batch.json` 保存。`discovery_judgement` 必须包含 `judgement`（新批次只允许 `not_exhausted`）。checkpoint 的 `run_status` 必须与同一时刻的 manifest 和批次 JSON 一致。缺少必需键时，生成器必须报错或以 `stop_reason=error` 停止，不得静默渲染为空值。

`events` 是事件数组，每条至少包含 `timestamp`、`kind`、`source_id`（可选）和 `details`（可选对象）。`kind` 使用开放字符串；推荐值包括 `source_discovered`、`source_opened`、`opened_metadata_only`、`open_failed`、`cache_hit`、`excluded`、`candidate_extracted`、`candidate_rejected`、`track_evaluated`、`checkpoint`、`review`、`diminishing_returns` 和 `operational_pool_exhausted`。`source_opened` 事件的 `details.access_level` 必须为 `full_text`；`opened_metadata_only` 事件的 `details.access_level` 必须为 `metadata_only`，且 `details.document_version` 必须说明摘要、索引或元数据范围。每达到来源 `batch_size` 边界必须记录一个 `checkpoint` 事件，`details.opened_since_last_checkpoint` 必须等于 `batch_size`；最终 checkpoint 事件可以小于该值。`source_discovered` 的 `details` 必须包含 `layer`（`layer1`/`layer2`/`layer3`/`adaptive`）、`query_id`（触发发现的查询 ID；连接器未提供时显式为 `null`）和 `position`（从 1 开始；未知时为 `null`）。缺少 `query_id` 时必须加入 `quality.warnings`，因为来源打开优先级无法审计。`adaptive_query` 事件只记录查询 `id` 及其 `trigger`（可选），不得写入 `produced_new_sources`；该字段以 `checkpoint.search_progress.adaptive_queries` 为唯一权威。每个 `search_progress.adaptive_queries[*].id` 必须在事件中恰好出现一次，反之亦然；缺失、重复或多余事件均视为批次一致性错误。

`problem_definition` 位于对应案例对象内，键为八个问题定义字段；每个字段值包含 `value_text`、`quote`、`location`、`source_id`、`evidence_level`、`confidence` 或缺失 `reason`。calibration 使用文档模型，production 迁移时再展开为 `case_problem_definitions` 行。

`failure_class` 允许 insufficient_evidence、failed_admission、classical_infrastructure、not_a_real_world_problem、not_modelable_as_nonlocal_game、classical_workaround_exists、problem_definition_incomplete、not_an_application_case 或 null。语义由 `passed_admission` 共同确定：0 时为准入失败原因；1 且归一分为 null 或低于配置快照阈值时为评分失败原因（当前为 insufficient_evidence）；1 且达到阈值时必须为 null。

`search_progress` 必须包含 `seed_completed`、`seed_pending`、`seed_not_applicable`（含原因）、`seed_executed_outside_scope`（含原因）、`adaptive_queries`（含 id、trigger、rationale、keyword_or_source、hits、opened、produced_new_sources、status）、`adaptive_converged` 和 `loop_status`。`produced_new_sources` 对新批次必须是非负整数，表示该查询触发的去重后 `source_discovered` 数量；它必须等于使用相同 `details.query_id` 的 `source_discovered` 事件去重数，由渲染器核对。自适应查询必须去重并可追溯到具体线索；`adaptive_converged` 和 `loop_status=converged` 只保留查询诊断，不参与证据充分判断。空列表合法，但不能满足收益递减条件。

`sources_unattempted` 必须等于 `discovery_sources - attempted_sources`。当其大于 0 且 `opened_sources < analysis_limit` 时，必须写入 `quality.warnings`，并不得声明操作耗尽或收益递减；analysis_limit_reached 仍按真实正文计数判断。

## 停止契约（当前版本）

运行中 stop_reason=null、checkpoint.completed=false；manifest、顶层和 checkpoint 状态必须一致。
未知停止枚举报错；`evidence_coverage_sufficient` 尚未启用。历史说明见 [CHANGELOG](../CHANGELOG.md)。

| stop_reason | 可计算条件 | run_status / checkpoint.completed |
|---|---|---|
| analysis_limit_reached | 去重正文打开数达到配置上限，与全文事件一致 | completed / true |
| max_cases_reached | 当前纳入案例与 previous_accepted_case_ids 的并集达到阶段上限 | completed / true |
| case_coverage_complete | 全部配置案例逐个通过同案例同 Track 覆盖及机器自检；人工状态不阻塞 | completed / true |
| budget_exhausted | 在线轮次、时间或总模型调用预算到限，保存 budget_cause | incomplete / false |
| diminishing_returns | 无待处理种子、来源或分段；末 N 条不同成功查询均无新来源 | incomplete / false |
| operational_pool_exhausted | 无可执行操作或未尝试来源；提交完整 actions/endpoints/rationale | incomplete / false |
| user_aborted / error | 用户中断 / 不可恢复错误，保存原因及恢复点 | incomplete / false |

previous_accepted_case_ids 必须来自已验证批次/数据库，不得伪造。completed 不代表证据充分。
`checkpoint.stop_evidence` 的操作性举证：

- diminishing_returns：`basis="new_sources"`、`window_query_ids` 精确等于末 N 条不同成功查询 ID、非空 rationale。N 来自当前配置；失败请求不算零新增，分页不算独立查询。
- operational_pool_exhausted：actions 覆盖种子、分页、引用扩展等全部剩余分支，每项有唯一 id、completed/failed/blocked 及 reason；seed_pending 必须有 failed/blocked 记录，不得藏匿 pending/running 操作。endpoints 逐项记录 id、实际 pages_fetched 和 limitation，rationale 非空。
- 两者均要求 sources_unattempted=0，不得把限流、无分页能力或当前端点限制解释为全局耗尽。
- budget_exhausted：`budget_cause` 保持真实原因，`calls_by_category_at_exhaustion` 为本次 invocation 耗尽时的累计调用分布，分类不是硬配额。

## 源接地审计

可选顶层 `grounding_failures` 是失败候选的审计数组，新验证门的失败必须追加于此，
不能只留在终端输出。每项含 case_id、field、source_id、failure_type 和原 candidate。
failure_type 为 citation_mismatch / quote_not_found / semantic_mismatch / source_not_opened_in_run /
source_mismatch / source_text_unavailable / invalid_evidence / counter_evidence_invalid。标识本身无效时可为 null，
原候选仍需保存。也可增补 quality.warnings 的 grounding 分类供人工注意。

validated_candidates 的 semantic_status/location_status 保留 unverified；字符串接地与语义复核的区别见[证据协议](evidence.md#写入前的源接地验证门)。reviewer/verifier、结论、上下文与理由随复核保存。
历史无文本快照的批次不会被自动补写“已验证”，只显示未执行该检查。

## 案例覆盖与在线导出

case_coverage_complete 必须遍历全部 configured_case_ids，由 `coverage_policy.py` 为每个案例独立重算：同一案例八字段 covered 或有
applicability_reason 的 not_applicable，再遍历该案例的 Track，要求四准入均有已复核证据。
准入值可 true/false；全 true 才要求该 Track 最低有效评分维数，否则不要求评分。
`checkpoint.stop_evidence.coverage_witness` 保存重算的 case_id、track_id、passed_admission、
valid_dimensions 和 decision_chains。不接受跨案例或跨 Track 合并，也不接受空集合的 all()。
每个配置案例都必须有完整覆盖链并通过原始记录 self_audit；缺任务、缺来源或无证据不能算完成。
顶层 configured_case_ids 与 cases 的 ID 集合必须一致；stop_evidence.configured_case_ids 保存固定顺序。
case_completions 按该顺序保存每案例 coverage_witness、self_audit、case_audit、human_audit_status。
单案例可只用原单数结构；在线导出总是写 case_completions，单数键为首案例兼容别名，须一致。
人工抽查不阻塞搜索停止。sources_unattempted 可以大于零，未尝试来源、未处理分段和缺口继续保留；
completed 只表示本次配置范围内覆盖停止，不表示准入/评分达标、所有来源处理完毕或全局证据充分。
`stop_evidence.case_audit` 和其中的 `human_audit_status` 是停止当时的只读历史快照，事后补录不改写。
`attribution_check_count` 保存停止时追加式 attribution_checks 的长度；导出守卫按该前缀重算历史统计，
case_audit 若存在须匹配，但不要求 audit_passed=true；self_audit 必须通过且绑定重算覆盖链。
`cases[*].human_audit_status` 和 case_audit 则按最新全部 attribution_checks 重算；不得以停止快照覆盖当前标签。
候选去重、链外错误、状态和阈值算法见 [证据协议](evidence.md#自检人工与成本)。

问题定义和 `tracks.<id>.criteria_evidence/score_evidence` 中每项含原证据字段及
`attribution_review`（attribution=attributed、attribution_reason）及 `semantic_review`（supported、location_checked=true、domain_rule_met=met、domain_rule_reason）；两者分别有 reviewer_kind/reviewer_id，并绑定同一 report_id/candidate_index、case_id、value_text、location、source_sha256，候选 grounding.source_sha256 必须一致，
coverage_status 为 covered/not_applicable；后者只允许有正文支持的问题定义。
对应 source_id 必须是 opened，无冲突；标志或缺失 reason 本身不构成覆盖。

`export_batch.py` 只输出同一运行已复核且无冲突的事实；不导出旧候选为已证实数据。
预算停止原样保留，并在 stop_evidence.budget_cause 记录具体限额。

在线 export_version=2 的 review_audit 保存 attributions、reviews 和 attribution_checks，包含未通过的判断。
quality.attribution 给出 attributed/abstained/absent/pending_attribution、eligible_supported、audited_samples、
audited_correct/audited_incorrect、attribution_precision 和 audit_coverage。
无人工样本时 attribution_precision=null，渲染 unknown；统计含义见[证据协议](evidence.md#自检人工与成本)。

quality 可含 cost_breakdown 分类账本；attribution 含审计阈值、required_audit_samples、audit_warning。
具体含义见 [证据协议](evidence.md#自检人工与成本)。

在线导出附 config_snapshot/config_sha256；覆盖守卫校验摘要后按 workspace 快照重算，避免安装配置变化改变审计门。

error 停止可在 checkpoint.operational_cause 与 stop_evidence.error_kind 标记 contract_violation；
这是模型输出细分类，不新增 stop_reason 或 warning category，仍为 incomplete/completed=false。

## 四服务引用身份导出

sources[*].citation_identity 保留 state/reason、expected_title 和 checks（实际执行的每服务结果），
cross_check 为 disabled/citation_unverified/cross_check_partial/cross_check_verified/cross_check_conflict。
身份判定及来源准入见[身份与扩展流程](workflow.md#引用身份与扩展)；冲突的 source_depth=unverified，grounding_failures 保留 citation_mismatch。
关闭引用服务时仍记录 source.metadata_identifier_conflict 和 trace_consistency 警告，保留 URL/发现元数据标识；identity 仍为 unknown/backend_disabled，不阻止入图，不把本地线索冒充外部核验。

quality.citation_identity 记录 enabled_backends、status、scope、requests_consumed、max_requests；
关闭时明确未启用且不生成 citation_unverified，启用后 unknown 才警告。部分核验与冲突有独立 warning category。
每请求回执在 adapter 的 online.citation_requests 和 citation_identity 事件中保留，导出不反写事实。

## 派生诊断与问题定义完成度

缺失问题字段的 reason_source=explicit_gap 只来自原始 gaps 的非空 reason，否则为 none、reason=null；完成度语义见[问题定义](evidence.md#问题定义)，历史批次不自动重写。
quality.model_calls 区分 invocation/workspace；cost_breakdown 保留 workspace 累计及未知价格，人工质量标签见[证据协议](evidence.md#自检人工与成本)。
round_interrupted.pending_stage优先最早无响应call_id（awaiting_response）；均已响应但下一步受预算阻止为next_stage_blocked_by_budget，契约拒绝为contract_rejected；非模型中断无对应阶段为null。
field_diagnostics仅派生已记录的多原因；not_attempted/diagnosis_unavailable不是失败计数，单篇无候选不是案例缺证结论，provided_segments不等于整表复核完成。引用响应保留实际哈希/范围，2MB超限前缀不能冒充完整响应；日志不保存密钥。
