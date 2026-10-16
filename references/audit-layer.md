# 审计层与产物布局

> 本文件唯一维护：反证报告、机器自检、人工审计、成本含义及产物追溯。跨职责规则通过链接引用其权威文档。

搜索、在线补证和复盘报告使用本契约。运行时依赖不变；QuantumNovelty 仅作审计设计借鉴，
不执行它的模型循环、技能链或专利流程。确定性自检不是额外独立语义评审，也不替代人工抽查。

## 审计实现分层

单条复核层 `review_policy.py` 检查候选归属/语义判断的绑定；覆盖聚合层
`coverage_policy.py` 重算同案例同 Track 的完整覆盖链；审计阈值层 `audit_policy.py`
执行自检、人工样本阈值与标签派生。三层均不提供语义正确性保证。
接地核心为运行时加载的 `assets/quantum_grounding/executor.py`，CLI 入口是
`scripts/validate_grounding.py`；在线经 adapter 直接执行该 access skill。

## 反证与决策链

在线 `review_contract=4`。每项语义判断必须包含结构化 `counter_evidence_search`：

```json
{
  "segments_searched": ["paragraph:1", "paragraph:2"],
  "negation_found": false,
  "conditional_limits_found": true,
  "threat_model_boundary_found": true,
  "negation_evidence": [],
  "conditional_limits_evidence": [{"location": "paragraph:1", "quote": "only under this condition"}],
  "threat_model_boundary_evidence": [{"location": "paragraph:2", "quote": "trusted devices"}],
  "contradictions_found": [],
  "summary": "说明所检索的否定/限制词、每项发现和对候选结论的影响；此处仅为格式示例"
}
```

新模型响应的 summary 长度为 1–2000 字符，超限走现有最多一次格式修复并消耗总预算；历史记录不截断。
发现却无法提供合规短引属于 counter_evidence_unsubstantiated 契约失败，不能改报 false，也不能用 abstain 跳过 true 必须举证的校验。`suppressed_findings` 按 candidate_index 比较修复前后同一候选的 negation_found、conditional_limits_found、threat_model_boundary_found，拒绝这三个 flag 的 true→false。它不比较 contradictions_found 列表或 summary；修复将矛盾列表从非空改为空、删除个别矛盾或改写摘要，不在此防护范围内。结构/接地校验能拒绝当前响应的无证据 true 和无效短引，但不能发现被删掉的矛盾，也不证明首次响应没有语义遗漏。原响应和实际字符数保留，batch.grounding_failures 以 counter_evidence_invalid 链接失败调用，不把失败当准入 false 或正文不存在。

反证报告原样保存；摘要语义质量由复核者判断，不使用中英关键词正则生成质量警告。
布尔字段严格校验；分段列表和 summary 不能空白，必须包含候选位置且属于实际提供的正文。
只声明本次提供分段的搜索范围，不声称已搜索未打开的全文。结构化记录证明可追溯性，
不能证明模型实际执行了所声明的搜索，也不能证明反证充分或穷尽。
前三项 found 是严格布尔值；true 时对应 negation_evidence / conditional_limits_evidence /
threat_model_boundary_evidence 必须有至少一项，false 时只能为空。contradictions_found 同为对象列表。
每项必须有 location 和 1–50 字符短引 quote；location 属于 segments_searched，短引通过共用字符串门
在对应原始分段匹配。空 finding 列表可省略。旧字符串矛盾列表不适用于新执行，历史记录不改写。
这只加强位置/引文可追溯性，不用关键词规则判定搜索是否实际发生或语义是否充分。
发现限制/矛盾时须说明其影响并据此决定 supported / abstain / semantic_mismatch。

`review_policy.supported_pair()` 统一检查归属、语义、绑定和 reviewer 身份；不要另写宽松守卫。

覆盖 witness 的 decision_chains 包括八字段、该 Track 四项准入，以及通过准入后采用的评分维度。
链保留候选键、来源哈希、双复核理由和反证报告。`self_audit(case_id, track_id)` 从原始 grounding、
attributions、reviews 重算必需单元格与冲突状态，再检查存档正文及当前打开正文的哈希，并从原始请求重算接地候选、引文位置和跨度，拒绝被改动的回执。
不接收 decision_chains 快照作为真值。缺项或正文变动时拒绝 case_coverage_complete，记录 online.events，
在剩余预算内继续；预算约束仍有效，不无限重试。拒绝分类为 unknown_target、missing_coverage、hash_mismatch、body_changed、invalid_binding、invalid_grounding（回执重算不一致）；失败含 missing_fields，missing_coverage 列出缺复核证据的具体字段。

## 引用身份三态

正文打开后、入图前按显式 allowlist 核对 DOI/arXiv 与声明标题，默认关闭。
三态、跨服务冲突/部分核验、版本、回执、节流、缓存与许可证边界由
[四服务身份契约](citation-identity.md) 唯一维护；服务结果不是正文证据。
unknown 不阻止候选入图，mismatch/冲突阻止相关来源的候选并保留 citation_mismatch；
未启用时注明 disabled，不产生服务失败警告。配置/恢复不得改写历史基线。

## 双审调用来源

在线 attributions/reviews 的 model_call 保存 call_id、model 和白名单 parameters：temperature、max_tokens、
top_p、seed、timeout、max_retries；未知值保留 null，不保存密钥或任意 SDK 配置。
quality.attribution.same_model_used 为 true/false/null，并记录 model_pairs_recorded/model_pairs_unknown；
null 表示没有可比较模型记录；模型对口径包括有有效绑定但被拒绝的双审，不仅统计入图候选。comparison 展示实际模型名和 same_model_used。不同 reviewer_id 或不同模型名都不保证误差独立。
人工导入和旧记录没有模型来源时保持未知，不补造调用信息。

## 成本与人工审计

按 call_id 关联开始和响应，按 extraction / attribution / semantic / orchestrator / other 汇总。
ContextGem 内部请求、修复请求和无响应的失败尝试都计调用；未知 usage/价格不视为零。
USD 只汇总后端或 SDK 返回的 cost_usd/response_cost，不自行假定模型价格；SDK 成本不是账单核对结果。
comparison.md 和 online.json 均展示成本分类。总 max_model_calls 是唯一调用硬上限，不按类别分配固定配额。
分类累计和每轮增量分别记录，预算耗尽时保留 calls_by_category_at_exhaustion。

scope.yaml 的 audit 配置控制覆盖率及最低样本数。最低抽查数为
`min(eligible, max(min_audit_samples, ceil(eligible * min_audit_coverage)))`。
零候选时覆盖率和精确率为 unknown，无不足警告；小于三个候选时检查全部即可。
低于最低覆盖率或样本数均警告，低于 warn_if_coverage_below 标为 critical。
当前 witness 按 (report_id,candidate_index) 去重统计；人工阈值仅用于质量标签，不阻塞覆盖停止。
状态为 not_applicable（空链）、unverified（未抽查）、partial（样本不足）、verified（达标且无错误）、
rejected（链内或该案例任意链外候选被人工判错）；off_chain_rejected 单独标记链外错误。
未形成完整 witness 时按当前支持的候选统计；尚无支持候选的案例仍标 unverified，不能推断已获豁免。
case_audit.audit_passed 仅供下游使用（verified/not_applicable），停止门只读 self_audit.audit_passed。
`invocations[*].stop_evidence.case_audit` 是只读历史快照，按停止时记录前缀验证，补录不改写。
`cases[*].human_audit_status` 是最新 attribution_checks 的派生汇总，每次导出重算，
audit-attribution 提交后立即返回重算标签；下次渲染展示新状态，不重新执行 stop_decision。
SQLite 同名列是派生缓存，生产导入/同步必须重算；冲突以 attribution_checks 为准，不能独立编辑。
自动搜索不创建 human 记录、不等待人工；只有用户主动提交抽查记录才改变人工标签。
搜索全自动完成且无人抽查时为 unverified；rejected 保留审计历史，下游默认排除。
系统性错误仍按 review.md 的 5% 暂停规则处理下一批，不改写历史搜索。
人工抽查须有绑定一致的 human 记录；agent 自检不计。满足阈值不表示随机抽样、统计显著或总体精确率已获保证。

## 预算与派生诊断

round_interrupted.pending_stage 优先取本轮最早没有 model_response 的 call_id，pending_kind=awaiting_response。
如果已发调用全部有响应，而下一次模型调用在发出前被预算阻止，pending_kind=next_stage_blocked_by_budget；
因此 8 calls / 8 responses 也可有待处理 semantic。非模型中断无对应阶段时为 null，不虚构未响应调用。
这两个字段只在事件与派生报告中使用，不增加独立事实表。

问题定义缺项的 reason_source 在导出时派生：只有原始 gaps 中非空 reason 才为 explicit_gap；
否则为 none、reason=null。没有 record-gap 不生成 pipeline 默认 reason，也不把单篇模型缺失观察升级为案例结论。
problem_definition_complete 只认可证据值或 explicit_gap；后者代表审计完整，不生成证据或覆盖停止资格。
硬阻塞字段定义见 [证据协议](evidence.md#问题定义)；case draft 只展示显式缺失原因。
reason_source 不写回 adapter gaps 或生产 SQLite；schema.sql 和生产库不因此迁移。
assessment 的字段名范围、版本、total_segments 仅记录在 online.events；继承/扩展保留历史 assessment，
不复制正文或 target_cells 全量事实，不增加模型调用或预算。

多表诊断均从在线事件派生：quality.model_calls.by_table 按 case_id/table_id 列出本次与累计分类调用，
无范围的历史调用保留未归属项，不推测归属。新调用显式记录范围；旧调用仅在同轮 assessment 后归属。
assessment_started.cursor_source 为 new、resumed（同范围续跑）、inherited（字段子集）、restarted（校验不符）；
历史事件缺此字段显示 legacy_unknown，不改写旧事件。comparison 展示案例/表和起始段，跨表第 0 段不是游标回退。
unprocessed_chunks 的触发条件不变，消息列出未完成案例/表；来源级已提供分段数不代表每张表复核完成。

## 配置追溯

生成 strategy/skill.md 的 frontmatter 含 config_sha256 和 UTC generated_at。
哈希沿用现有 `digest(domain_config)`：覆盖 tracks、exclusions、scope 和八字段定义，
不是仅对 tracks.yaml 文件字节求哈希。workspace 内配置与其哈希不一致仍报错；
与当前安装配置不同只 warning，继续使用 workspace 快照，不改写旧事实。

## 受控变更与不可变基线

受保护清单按版本另存 `protected-vN.json`，使用创建时的文件 SHA256；旧清单和旧运行不改写。
变更在独立分支/副本完成，每项提交记录影响、兼容性和对应新清单哈希。
新执行的 online.skill_baseline 使用 version=3，拆分 execution_baseline（scripts/config/assets）与
document_baseline（references/SKILL.md/CHANGELOG.md），各含 sha256 和 files。恢复要求相同执行基线和配置；
仅文档变化发出 warning，原始 baseline 不覆盖，每次 invocation 另记当前 document_baseline。
version=2 或无基线的旧执行不自动迁移，须归档 skill 恢复或新 workspace；测试文件不参与执行基线。
模型/搜索上游依赖仍以项目锁与源码修订固定，升级必须重验，见 [SearchOS 边界](searchos-boundary.md)。
缺基线的历史 workspace 仍可只读审计；新执行使用其存档 skill 或新 workspace，不补造历史基线。
同一运行期间不编辑其 skill；清理后的真实验证只用新 workspace。
删除 CHANGELOG 条目须说明删除内容、依据、新执行/派生视图影响及历史兼容处理；
不根据单次或多次未触发直接删除安全分支。

## 统一产物路径

所有默认生成产物以项目目录为基准，集中到：

```text
artifacts/quantum-scout/
  config/                   # 生成的在线配置、schema、env 模板
  runtime/                  # 依赖快照、清单
  validation/               # doctor、离线检查、在线验证、测试报告
  cache/sources/<source>/   # 无显式 workspace 的单来源下载
  tmp/                      # 项目内临时调试文件
  runs/<run_id>/            # 原生流程的 manifest、checkpoint 和 calibration
  workspaces/<run_id>/      # 在线运行
    state/quantum_adapter.json
    state/socm/             # 可重建的 SearchOS 状态/覆盖视图
    config/quantum_schema.json
    inputs/replay.json       # 可选历史候选回放输入
    reports/online.json
    sources/<source_id>/    # 本次打开正文及原件
    skills/                # 该配置版本生成的策略与字符串门
    calibration/           # batch、comparison、checkpoint
```

领域配置仍位于 skill 的 config/；不要把生成文件写入这里。显式 --workspace/--output 路径优先。
只支持 version=2 和上述规范路径；缺失/损坏状态或配置哈希错误明确报错，不猜测路径或自动迁移。
历史路径迁移和记录语义见 [CHANGELOG](../CHANGELOG.md)。
生产 SQLite 和正式 cases/ 不属于中间产物，本轮不迁移。

## 参考核查与采用范围

三个参考仓库已克隆到 /root；以下为本次核查的固定提交，不采用可变的 star 数或用户数作为技术论据。

- [QuantumNovelty](https://github.com/BoltzmannEntropy/QuantumNovelty/tree/2a9d348eaba90a626b91596d871c483a09bf99f3)：
  参考审计-证伪原则、chain/pipelines.py 的阶段判断、skills/common/llm.py 的 usage/cost 回执；
  它的多评审及严格支配计算不等同于本项目的确定性覆盖自检。
- [academic-research-skills](https://github.com/Imbad0202/academic-research-skills/tree/a3ef8c79d888b90aaaaecce7f42fbc3fd082d5ab)：
  协议描述 0.70 标题匹配；当前 _text_similarity.py 同时包含 SequenceMatcher 等演进逻辑，
  采用四索引及标识/标题交叉检查原则；客户端许可/重试契约不符，本地实现独立，详见 [复用评估](citation-identity.md#参考与直接复用评估)。
- [scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills/tree/a1043ef544e3a100c28e70a736b6cf32554d0677)：
  可见 metadata.version 约定；config_sha256/generated_at 是本项目的配置追溯实现，不冒称上游已有同一协议。

抽取候选逐条执行原 Candidate 契约，违规原值、位置、验证错误及 call_id 写 contract_rejection；不截引文、不改置信度。
ContextGem 在库的批量类型验证前隔离候选，合法候选仍需句子映射、grounding 和双复核。原始响应与过滤响应均保留。
全候选违规归 stop_reason=error、operational_cause=contract_violation、stop_evidence.error_kind=contract_violation；
中断 pending_kind=contract_rejected。空抽取不等于违规。结构损坏仍按原有限修复/降级边界处理，不额外追加调用。
quality.contract_rejections 统计候选和受影响调用，部分有效的调用不能统称浪费。离线回放仅报告可保留候选，不声明游标推进或复核通过。

契约拒绝是入图前执行层安全拒绝，不等于人工确认的证据错误；所消耗调用照常计入 cost_breakdown，人工不一致率只统计人工已复核样本。

quality.field_diagnostics 只读派生 case_id/table_id/field 的多原因分布，来源与观察事件/报告绑定保留在 sources 明细。
no_candidate 只计明确 field_gap_observation，已记录的同批契约/定位拒绝不重复算无候选；无足够轨迹为 diagnosis_unavailable。
not_attempted 仅表示本 workspace 账本没有该字段尝试记录，不表示正文不存在证据。review_pending 不冒称复核拒绝。
context_presentations 是实际提供上下文次数，shared_extraction_calls 是字段共享的抽取调用次数（不可跨字段相加）；
grounded_candidates、attribution_records、semantic_records 分别是候选/复核记录数，不冒称付费调用数。
provided_segments 不等于已处理完成；只有匹配当前范围、版本和分段数的 assessment=done 才报告“分段已处理，字段无证据”。
诊断不联网、不新增事件、不写 gaps、不改变判定、不自动重抽。构造响应 CLI 测试单列为受控集成，使用可丢弃临时项目，禁止污染真实运行记录。

not_attempted 与 diagnosis_unavailable 是状态而不是失败计数；reasons 只计实际记录，禁止用“没观察到”虚增一次失败。

问题定义字段 business_problem、classical_baseline 分别更名为 real_world_problem、existing_practice；现实场景包含产业、研究部署和公共部门，既有方案不替代 Track 的经典基线门槛。
轮次效率只读按 round_completed / round_interrupted 的字段增量与调用事件派生；拒绝影响的共享抽取调用不可全部视为浪费。剩余轮次仅按未处理分段给出条件下界，done 仍缺证时无法预测补全轮数，不自动重抽。
