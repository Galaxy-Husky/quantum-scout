# 搜索与入库流程

> 本文件唯一维护：搜索/评估/入库顺序、阶段控制、准入与评分汇总。跨职责规则通过链接引用其权威文档。

## 初始化和阶段控制

读取 Skill 的 config/*.yaml；用户明确提供项目配置或 --config-dir 时使用覆盖层。
默认 pilot / calibration。上限、行业、batch_size 从当前 phase 读取；max_cases/target_cases
表示阶段累计纳入上限，不是本批增量。production、阶段转换和正式复盘需明确授权。

创建 artifacts/quantum-scout/runs/<run_id>/manifest.json，保存配置快照和 config_hash，状态 preparing。
开始搜索/评估时改为 running。准备不是完成；必须继续执行下述循环。
calibration 不建库、不写正式 cases/reviews 或 production 来源日志。
production 库不存在才创建 schema，已存在先检查；连接启用 foreign_keys。
只读查询使用 SQLite URI mode=ro。

## Run 生命周期与停止

先检查用户中断、不可恢复错误和硬预算，再调度未处理来源/查询。
正常 checkpoint 是恢复点，不是暂停点；每成功打开 batch_size 个正文来源写入增量
checkpoint 并更新 comparison 后继续。最终 checkpoint 可以不足 batch_size，事件 details.final=true；这不改变 incomplete run 的 completed=false。

停止值、状态、覆盖条件和操作性举证统一见 [批次停止契约](batch-schema.md#停止契约当前版本)。
completed 只表示本次预算/阶段条件达成，不表示全部案例证据充分；历史演进见 [CHANGELOG](../CHANGELOG.md)。

## 调度、查询与操作性停止举证

依次处理未尝试的相关正文来源、适用 SEED-*、由已打开来源的引用/作者/术语/机构
及字段缺口派生的 ADAPT-*。发现顺序和打开顺序可不同；优先与当前 Track/行业
相关的直接来源。Coverage Map（使用时）帮助排序缺口；案例覆盖停止由独立复核事实逐项重算，不使用汇总覆盖率。
八字段有原始 record-gap 的显式 reason 才代表审计完整（导出 reason_source=explicit_gap），不补默认原因；missing/uncertain/unreachable 不能算 filled。
新增案例必须扩大覆盖分母，不能通过删除困难案例制造进展。

configured_seed_queries 是种子，不是完整搜索空间。每项保存查询、hits、opened、
实际 pagination_pages 和 completed/failed/not_applicable；不适用项保存原因。
跨行业方法查询必须解释如何服务本轮行业；越界执行记 seed_executed_outside_scope。

ADAPT-* 必须有 trigger、rationale、keyword_or_source、hits、opened、produced_new_sources、
status、端点与实际分页记录。新增数按整个 run 已见 source_id 去重，不能把种子已发现
来源再次计新；查询事件必须早于其发现事件。空自适应列表是合法中间状态，也可在
预算已达时结束；空列表不能满足收益递减条件。

N 读取 phases.<phase>.diminishing_returns_threshold 并复制到 counts；在线对应 stall_rounds。
失败请求不能算零新增，分页不能算独立查询。停止举证结构仅在 batch-schema.md 维护。
无有据可查的终止条件则继续，不为凑满上限重复失败搜索。报告列出缺口和恢复条件，不声称全局耗尽。

## 完成度验证边界

生成器与渲染器的停止契约见 [batch-schema](batch-schema.md)，执行层级见 [SKILL](../SKILL.md#约束执行层级)。
max_cases 的累计计数由本批纳入案例与 previous_accepted_case_ids 的并集计算；
历史案例 ID 必须来自此前已验证的批次/数据库，不可填假 ID 凑数。
操作性停止不是阶段转换授权，不触发自动 production 或正式复盘。

failure_class 保持原八类：insufficient_evidence、failed_admission、classical_infrastructure、
not_a_real_world_problem、not_modelable_as_nonlocal_game、classical_workaround_exists、
problem_definition_incomplete、not_an_application_case。领域规则见下文，不因框架变化放宽。

## 来源与案例的关系

来源（`source_id`）是论文、专利、报告或网页等证据材料，来源数量绝不等于案例数量。 `discovery_pool_size` 是累计去重后的 source_id 数量；它可能在 run 结束时等于 `opened_sources`，必须结合中间 checkpoint 的 `sources_unattempted` 判断发现和打开是否曾分离。 报告必须同时给出 `attempted_sources` 和 `sources_unattempted`；若 `sources_unattempted > 0` 且 `opened_sources < analysis_limit`，除非预算已达或用户中断/错误，仍须先处理未尝试来源；不能声明操作耗尽。一个实际应用案例（`case_id`）可以由多个独立来源共同支持，一个来源也可以抽取出多个不同案例。来源与案例是多对多关系，正式库用 `case_sources` 保存每条关联、来源角色、支持的准入/评分项和证据层级；`case_sources` 是唯一的来源关联事实表。流程必须先记录并打开来源，再从来源中抽取候选应用场景，按实际场景、任务和参与方去重生成唯一 `case_id`，最后才对 `(case_id, track_id)` 做准入和评分。

以下 phase 上限适用于 agent 按 scope 执行的流程；在线 runner 采用独立在线 JSON，不自动读取 phase 上限，doctor 与 batch 的 quality.limit_policy 显示来源及参考值。

`analysis_limit` 从 `scope.yaml` 当前配置读取（若当前 phase 在 `phases.<phase>.analysis_limit` 提供覆盖，则使用该值），表示成功打开并读取正文的来源数上限；一次 run 必须持续尝试发现池中的来源，直到成功打开数达到该上限、阶段累计纳入案例达到 `max_cases`/`target_cases`，或满足上文的可审计操作性停止条件。打开失败、仅有元数据、验证码/授权阻断或其他未读取正文的状态不计入成功打开数，也不消耗上限，不能因这些失败提前结束来源分析。纳入上限读取当前 phase 的 `max_cases`，报告中可将其称为 `accepted_limit`。phase 上限同样只从 `scope.yaml` 当前 phase 配置读取；不得在流程文档中另行假定数值。报告必须分别给出发现来源数、尝试来源数、成功打开来源数、抽取候选案例数、完成问题定义的候选案例数、去重后唯一案例数和纳入案例数，禁止用来源级准入结论替代案例级准入结论。

## 搜索、排除、缓存

search-strategy.yaml 是当前 agent 规划输入，在线 runner 不自动读取。layer1 的 url 是已知正文，使用 open-source；query 是普通 Web 查询，交由共享 SearchOS provider。scripts/searchos_seeds.py 可无网络导出动作；拒绝旧 arXiv:/author: 专用语法，不把 ID 种子误当搜索语法。layer2/3 的领域与关键词仍由 agent 按实际缺口生成查询。

按当前行业从 layer1 → layer2 → layer3 搜索论文、专利、技术报告、白皮书。full 的 all 指 search-strategy 中领域并集，经用户复盘确认可更新映射；不得扩展到排除领域。先匹配 domain/sub_domain/title/abstract/keywords，大小写不敏感、按词或短语匹配，保留实际命中片段，歧义保留待核查标签，不能只凭子串误排或等待人工阻塞搜索。

命中政策写 excluded_by_policy；其余才查已处理 source 缓存，命中只记 cache_hit 并跳过分析。seen_sources 仅标记已完成处理来源，不将打开失败或中断当完成。单个 source 可包含多个不同实际应用案例，首次分析应完整提取；唯一 case_id 按三个要素去重：业务任务、参与方结构与威胁模型、物理约束（距离、拓扑、信道）。任一要素有显著差异即保留为不同案例，三者全部相同才合并；同一业务任务的不同技术实现（如 DI-QKD 与 MDI-QKD）保留不同 case_id。同一技术族可填写 sub_domain（如 qkd-di、qkd-mdi、qkd-time-transfer）供客户分组。发生合并时，在 candidate_rejected 事件中记录 canonical case_id 及三要素比较依据，不能只写“重复论文”。`case_id` 使用稳定格式 `<domain_code>-<seq>`：`domain_code` 为 3–4 个大写字母领域代码，`seq` 为该领域内四位递增序号（从 0001 开始），例如 `TEL-0001`、`FIN-0003`、`GRID-0012`。Track 不编码进 ID，因此一个案例同时通过两个 Track 时仍只保留一个稳定 ID，并在 `case_tracks` 中保存两行。

每个来源只记与实际操作对应的 `opened`、`opened_metadata_only`、`open_failed`、`excluded` 或 `cache_hit`。来源是否产生纳入案例不通过来源结果枚举表达。政策拒绝可基于已打开元数据页，不得声称读过未打开全文。找不到内容不虚构结果或 token_cost，未知消耗 NULL。

## 问题定义抽取与验证

问题定义的八字段语义、关键字段硬阻塞、显式缺失原因及部署边界统一见
[证据协议](evidence.md#问题定义)。八字段审计完整后才执行 Track 准入；
被拒的定义候选只保留拒绝记录，不创建 admission/score、case_tracks 或评分统计。
calibration 将字段内嵌到案例对象；production 按 `(case_id, field)` 逐行写入
case_problem_definitions，之后关联案例来源及发现轨迹。原始 gaps 与导出 reason_source 的
区别见 [审计层](audit-layer.md#预算与派生诊断)，禁止用默认 reason 补齐完成度。

## 数据一致性前置条件

部署字段写入前遵守 [证据协议的前缀与阶段复制规则](evidence.md#问题定义)。

写入 `case_evaluations` 前，应用层必须验证对应案例的八字段问题定义已完整；`problem_definition_complete=0` 时拒绝写入并记录拒绝事件。每组写入 `case_evaluations` 的 `(case_id, track_id)` 最终必须有对应的 `case_tracks` 行；批次结束时若存在孤儿评估记录（有评估但无汇总行），视为批次写入失败，必须回滚或标记 `error`。

写入 `case_tracks` 前，对应 `(case_id, track_id)` 的全部准入记录必须存在：Track A 的 4 条 `kind='admission'`（C1–C4）或 Track B 的 4 条 `kind='admission'`（S1–S4）。若准入通过，还必须写入该 Track 的全部评分维度（Track A 5 条、Track B 6 条 `kind='score'`）；缺任一记录都拒绝写入 `case_tracks`。每个问题定义字段的 `source_id` 必须已在 `case_sources` 中关联，保证字段证据来源属于案例来源集合。

## 字段语义说明

`excluded_cases.candidate_id` 使用与 `case_id` 相同的 `<domain_code>-<seq>` 格式，但该候选未落入 `cases` 表。`case_tracks.display_order` 用于同一案例多个 Track 的展示排序，取 0 或 1。

`search_log.result` 只描述来源处理事件：`opened` 表示成功读取正文，`opened_metadata_only` 表示只读元数据，`open_failed` 表示打开失败，`excluded` 表示命中政策且未打开，`cache_hit` 表示命中缓存；`checkpoint` 和 `review` 是运行事件。来源是否产生候选或纳入案例不写入 `search_log.result`，应通过候选事件以及 `case_sources` 与 `case_tracks` 的关联查询。

## 准入、评分、抽取

准入和评分是两个独立步骤。先写 `case_evaluations` 的 admission，再写 score，最后汇总写入 `case_tracks`。准入判断只基于该 Track 的 C1–C4 或 S1–S4 四值结果：全部为 `true` 时 `passed_admission` 必须为 1，只要有一个不是 `true` 就必须为 0；评分证据不足不得回改准入结果。若准入通过但评分证据不足，保留 `passed_admission=1`，将 `score_normalized` 设为 NULL、`failure_class` 设为 `insufficient_evidence`，并因未达到分数门槛而不计入 `accepted_cases`。若准入失败，记录具体准入原因，评分记录可以为空。一个 Track 失败不妨碍另一个 Track 按自身结果通过。

只有准入通过后，才按 tracks.yaml 维度独立评分，每维 reason 和可追溯证据；不得因研究者未给部署时间而自估年份。缺证处理与禁止推断补证见 [证据协议](evidence.md#禁止推断补证)。对每个 Track，`score_total` 为有效维度原始分之和，`n` 为有效维度数，`score_normalized = score_total / (n * 5) * 25`；为防止通过隐藏缺失维度抬高分数，Track A 至少 4/5 个维度、Track B 至少 5/6 个维度有 1/3/5 分，否则该 Track 不纳入。n=0 时两者 NULL。报告 n 和缺失维度，`max_score` 是 `score_total` 原始维度总分上限：`nonlocal-coordination` 为 25，`quantum-security` 为 30；两条 Track 的 `score_normalized` 均归一化到 0–25，归一化门槛均为 15。生成器必须拒绝以下矛盾：四项准入全为 `true` 却 `passed_admission=0`，或评分证据不足被写成准入失败。

至少一个 Track 全部准入且 `score_normalized >= 15` 才写 cases。`case_tracks` 可保留另一个 Track 未通过的评估记录，但展示归属、计数必须筛 `passed_admission=1` 且 `score_normalized>=15`。`display_track` 选择展示次序；写入 cases 时从该 Track 复制 `display_name_en` 和 `display_name_zh`，不影响按 `track_id` 筛选。所有评估粒度为 `(case_id,track_id)`。

两个 Track 均失败时分类：政策优先；经典基础设施 classical_infrastructure；综述/框架/纯算法 not_an_application_case；无法建模为非局域博弈 not_modelable_as_nonlocal_game；存在经典资源扩展方案 classical_workaround_exists；缺关键证据 insufficient_evidence；其余 failed_admission。若一个 Track 通过、另一个失败，保留失败 Track 的 `case_tracks` 和 `case_evaluations` 记录，设置 `passed_admission=0`，失败原因写入对应评估的 `reason`，不写入 `excluded_cases`。应用映射必须有文档支持，不能把理论算法改写成产业案例。抽取及入库使用 evidence.md 的证据协议。

`failure_class` 必须结合 `passed_admission` 解释：准入未通过时表示准入失败原因；准入通过但 `score_normalized` 为 NULL 或低于 15 时表示评分失败原因（当前允许 `insufficient_evidence`）；准入通过且达到分数门槛时为 NULL。渲染和下游查询不得单独解释该字段。

## Checkpoint、续跑和归档

每批计算同领域同维度评分分布并与历史比较。漂移阈值从 `tracks.yaml` 的 `drift_threshold` 读取；若未配置，只记录分布，不触发漂移告警。`primary` 记录数 / (`primary` + `secondary` + `ai_inference`) 记录数低于 60% 告警；分母只计有证据层级的记录，`NULL evidence_level` 不计入，分母为 0 时标记 N/A。`insufficient_evidence` 占本批准入记录比例高于 30% 告警；定量 quote 覆盖率低于 80% 告警；提交门槛见 evidence.md，非空定量字段必须达到 100%。没有证据的字段不应计为 primary。

输出候选数、纳入数、拒绝原因、缓存数、有效维度数、证据分布、定量覆盖率、已知 token 消耗及未知数量。状态按批次契约保持一致。calibration 保存符合 `references/batch-schema.md` 的 JSON（含运行配置、全部事件、评估、指标、checkpoint）及对比表到该 run 目录；渲染 comparison 时，同步为每个纳入案例生成 `calibration/cases/<case_id>.md` 单案例草稿；该文件由批次 JSON 派生，不是新的事实源。production 先验证再在单事务写 cases、case_tracks、case_evaluations、来源缓存、日志及拒绝记录，最后写 checkpoint 事件。`require_manual_review: true` 只在阶段边界触发：达到 `max_cases`/`target_cases` 后暂停并等待复盘；不因普通批次 checkpoint 自动暂停。失败回滚，不能把半批标记完成。

checkpoint 的字段契约见 [batch-schema.md](batch-schema.md)，停止证据亦在该契约维护。

批次 ID 采用 pilot-batch-01 等，并始终与 run_id 联合使用；产物写入 artifacts/quantum-scout/runs/<run_id>/calibration/ 和 artifacts/quantum-scout/runs/<run_id>/checkpoints/。manifest.json 记录配置快照及 config_hash；checkpoint 的字段结构见 `references/batch-schema.md`。resume_from 查同 phase/mode 的已完整写盘恢复点（可含 incomplete run），校验配置和事件一致，拒绝未知/半写入标识；checkpoint.completed 是 run 终止标志，不是恢复点文件完整性标志；同一候选和 case_id 重放不得重复计数。跨 mode 从校准转正式需要重新打开验证来源，不隐式复用临时日志。

从已提交数据库生成 cases/<case_id>/evidence.md：200–400 字摘要加逐项准入/评分/定量证据表及搜索路径；若完整证据超出字数，以完整审计优先，不能截断证据。注明 from_document/ai_inference，并在文末附 `case_id`、`run_id`、`search_log_ids` 数组和 UTC `generated_at`。导出失败从库重建，不回头改文档来掩盖数据库值。

达到阶段上限停止搜索并产出阶段复盘。production 在达到阶段上限时写 `reviews/<phase>-review.md`；calibration 在每个来源 checkpoint 完成时都在 `artifacts/quantum-scout/runs/<run_id>/calibration/` 更新 comparison，并在事件轨迹中保留 `checkpoint` 事件。没有复盘确认不得转阶段。full 没有后续阶段，但仍抽查证据。目标 200 是期望，不是最低准入数量。

pilot 复盘还必须单独报告来源打开层级：`opened_sources`、`opened_metadata_only` 及各自占比；当 `insufficient_evidence_admission_ratio > 0` 时按摘要层证据、文献未给出该项、语义判断困难三类归因并记录计数/比例，若摘要层证据占比超过 50%，下一批必须检查是否应将其标为 `opened_metadata_only`。pilot 复盘还必须单独报告：Track A 候选是否出现及其 C1–C4 失败分布；发现池大小与打开来源是否被人为相等、是否存在未打开队列；自适应查询 ID 在事件轨迹与 `search_progress` 中是否一致，以及 `produced_new_sources` 的最终值。零个 Track A 纳入案例、来源证据比例偏低或自适应查询多数无新来源都属于待验证现象，必须区分检索覆盖不足、文献分布和准入标准导致的失败，不得为了满足目标放宽准入标准。
