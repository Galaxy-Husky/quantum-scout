# 执行流程

本文件维护调用、调度与状态所有权。证据及评估语义见 [evidence.md](evidence.md)，输出与停止契约见 [batch-schema.md](batch-schema.md)。配置阈值来自 workspace 快照，不能为跑通放宽。

## 配置和调用

模型角色和搜索后端复用 SearchOS 共享设置；`--settings-file` > `SF_WEB_SETTINGS_PATH` > 所选 env 项目的 JSON > 安装默认值。显式文件损坏/缺失报错，不退回其他模型。`--env-file` 加载密钥，已有环境变量优先；不把密钥写入任务 JSON、日志或共享设置。

任务 JSON 配置候选、查询、预算及可选调度偏好；`cases` 是案例 ID 到 `{description, queries}` 的映射，description 明确协议/系统身份，不预填领域结论。queries 使用普通 Web 查询列表，省略 providers 继承共享选择。候选 ID 格式为3–4位大写领域代码加4位序号，如 SYNC-0001。`preferred_track` 可为 `quantum-security`、`nonlocal-coordination` 或默认 null；仅优先选择该 Track 当前可执行的准入/评分任务，避免另一 Track 拒绝先完成案例，不改变八字段前置、全 true 评分门或覆盖停止契约。

```json
{
  "cases": {"SYNC-0001": {"description": "核对指定时钟同步协议，不预设准入或分数", "queries": ["quantum clock synchronization"]}},
  "max_rounds": 5, "max_model_calls": 24, "max_seconds": 900,
  "call_timeout": 90, "max_context_chars": 20000,
  "citation_identity": {"enabled": []}, "citation_expansion_backend": "none"
}
```

示例不是付费授权。预算按实际 extraction、attribution、semantic 和其他请求累计；格式纠错及历史保真请求均计入对应类别，不另维护固定调用下界。以原生调用账本判断消耗，上限不保证完成。

从项目根运行，`--workspace` 每次使用明确的新路径：

```sh
.venv/bin/python skill/scripts/searchos_online.py doctor --config <任务.json> --env-file <本地.env>
.venv/bin/python skill/scripts/searchos_online.py open-source --config <任务.json> --env-file <本地.env> --workspace <全新workspace> --url <正文URL> --case-id SYNC-0001
.venv/bin/python skill/scripts/searchos_online.py run --config <任务.json> --env-file <本地.env> --workspace <全新workspace>
```

`doctor` 不联网；ready 只证明本地构造检查通过。`open-source` 不经搜索，仍执行完整抽取/双审/导出；可显式传 `--expected-title`，不自动取标题。`run` 会真实搜索并使用模型额度。
`semantic_output_format` 默认 `json_object`；已确认模型/服务支持时可显式设 `json_schema`。严格模式把现有语义契约仅放入 response_format，所有字段显式返回；候选编号限0，搜索位置及锚点ID限本请求目录，四类发现共用一份ID枚举（保留null），请求先列发现再给结论。JSON模式使用同一请求约束；本地 schema、锚点接地和双审守卫仍执行，服务拒绝或响应违规直接停止，不降级重试。第三十四笔当前网关已返回符合schema的结构，但发现标记与空列表不一致仍被本地守卫拒绝；不将 JSON 语法合法等同于结构或语义成立。

### 预算与失败处理

省略模型/轮次/时间时实现默认64次/5轮/1200秒，单操作60秒，输出最多4096 token；默认值不是授权。调用与时间按 invocation，正文来源上限、来源/查询恢复配额及引用 HTTP 按 workspace 累计；不从 scope phase 自动继承。实际请求计数见上文账本，模型 SDK 重试为0，语义评审无纠错；锚点与失败处理见[证据协议](evidence.md#原文证据绑定)。

| 情况 | 当前处理 |
|---|---|
| 正文 ConnectError | 原预算内等待1秒后重试一次；每来源累计最多2次尝试，与显式恢复共用上限。重试前持久化失败/尝试事件并重查时间预算。 |
| 429 或超时 | 停止该服务，不自动重试；恢复须另行授权，剩余额度不能授权重跑。 |
| 其他正文打开错误 | 不走 ConnectError 重试。固定 URL 最终打开失败为 error/source_unavailable，保留 error_type，不误记预算耗尽。 |
| 固定 URL 全部分段已处理但仍缺证 | operational_pool_exhausted；举证仅限本次固定来源/案例及禁止搜索的操作范围，不代表全局耗尽，不自动重抽已处理分段。 |

停止状态枚举及举证字段见[批次契约](batch-schema.md#停止契约当前版本)。

## 来源与调度

先处理未尝试的相关正文和未完成分段，再执行种子和从已打开来源/字段缺口派生的查询。layer1→2→3 是操作者策略，事件可供核对，不代表代码强制。失败请求不是零新增；来源数不等于案例数。
一份正文可支持多个案例，按具体任务、参与方/威胁模型和物理约束去重；案例归属与来源独立性统一见[证据协议](evidence.md#文档与独立性)。

正文下载保留原件、版本、提取模式及哈希。Poppler默认 reading order 不保证所有PDF正确；双栏/表格/公式/稀疏列有疑问时核对同版本页图。只读格式归一以接地门白名单为准，不放行OCR或语义改写。
发现时可合并官方arXiv abs/pdf等别名；显式版本URL打开不能被另版本缓存替代。不同DOI或未识别镜像不凭标题猜测同文。身份请求按完整版本缓存。

抽取使用ContextGem原生JSON数组格式，不要求服务端JSON Schema或maxLength支持。发送前为完整原文句分配本轮ID，句子仅在原正文视图出现一次，模型在value.source_quote_id中选ID，客户端按ID取回原文；不自由生成或截断证据、不截写既有引文、不自动换ID或引用句。完整原响应先保存，选项目录随请求落盘并校验哈希后读取，选择展开后经本地Candidate逐项校验；未知ID或非法项单独拒绝并保留原值，其他合规项继续，不增加请求或纠错。

仅 ContextGem 本地依赖不可用且尚未发出请求时，原生退路复用相同片段切分器和 source_quote_id 契约，程序从保存目录恢复所选原文证据及位置；未知 ID、回传文字或位置覆盖均隔离拒绝，仍须接地与双审。

每次最多8候选；先Candidate契约及保存请求的段落/句ID目录校验，再ContextGem引用句唯一映射，再接地，之后逐候选归属/语义双审，成功才投影。未知或跨段句ID拒绝整项候选，不删坏引用后接受原项；句ID目录仅本地保存，不增加模型输入。部分非法候选隔离并保留原值/错误/调用ID；全违规停止error/contract_violation，空抽取不是违规。句子映射失败不触发服务退路，不靠全文搜索换引用句或任取首个匹配。
ContextGem空白处理及语义评审锚点统一见[证据协议](evidence.md#原文证据绑定)。
同来源跨表不共享游标；抽取缓存绑定案例/表/来源版本/分段/字段范围。已获有效归属但缺语义只补语义；已完成双审不重复调用。仅匹配范围的全文处理结束才标done，异常保留本批起点。

## 评估调度

依次执行八字段问题定义、Track 准入和通过准入后的评分；前置门、缺证处理和部分评分见[准入与评分](evidence.md#准入与评分)，具体字段见[问题定义](evidence.md#问题定义)。停止时按[案例覆盖契约](batch-schema.md#案例覆盖与在线导出)逐案例重算，不跨案例或 Track 拼接。

## 宿主跨来源检索（sandbase）

按用户指定，优先由宿主临时读取 sandbase `multi-source-search` 指令、报告 schema 和原生 validator，不安装第二套运行时，不自建规则比对模块。仅在显式任务中调用，尚未成为原生 runner 的默认阶段。单一搜索渠道记检索局限，不以工具数量阻塞；上游 validator 只证明账本内部结构，不证明来源独立或语义正确。不同查询、搜索工具和镜像 URL 都不能代替[来源独立性核查](evidence.md#文档与独立性)。

宿主报告只作交接输入，不直接作为 calibration batch 或 Candidate 导入，也不成为第二个事实源：

| 上游字段 | 现有链路的交接方式 |
|---|---|
| sources[].id/url、claims[].source_ids | 外部 ID 留在原报告中；实际原文 URL 经 `open-source` 进入全新获准 invocation，取得原生来源记录。已读方法论论文不能替代具体案例的证据归属。 |
| claims[].text/kind | 作为待核查主张；inference 不补证，不将自由文本转换成准入 true/false。 |
| confidence、independent_source_count | 保留上游原值与独立性理由供审核；不按来源数给原生 Candidate 赋值，不自动将 high 降档以绕过契约。 |
| conflict、gaps | 供归属和语义复核核查；false 仅表示该检索范围未发现冲突，不能替代反证搜索；gaps 不能自动写成原生 record-gap 理由。 |
| 原报告未提供的 quote/location | 从对应原文重新抽取、接地并双审；宿主工具响应中的字符定位不等于原生正文接地。 |

本阶段复用已有正文入口与证据守卫；尚无自动账本导入或冲突字段注入评审的实现，不宣称其已通过真实链路验证。每次付费正文处理仍须逐笔授权，不因账本列出多个 URL 自动续跑。

## 引用身份与扩展

默认关闭。`citation_identity.enabled` 允许 crossref/arxiv/semantic_scholar/openalex；`citation_expansion_backend` 独立选择 none/openalex/semantic_scholar。旧citation_backend仍兼容，但不能与新allowlist重复配置。S2 key可选，匿名429不是缺key；本适配器的OpenAlex需OPENALEX_API_KEY。
DOI优先已启用Crossref，arXiv优先已启用arXiv；按需S2/OpenAlex补充，无标识不请求、不按标题搜索。Crossref404=unknown，不证明论文不存在。标题相似度>=0.70只是元数据启发式，正文资格独立核查。
verified要求标识/版本与expected_title一致；缺标识/标题/版本核验或访问受限为unknown；任一mismatch或跨服务标题冲突优先，拦截相关来源候选。unknown不降低正文资格；关闭时不伪造服务失败。多服务全verified与partial分别报告，未调用服务不补造回执。
每HTTP先持久占预算，身份/扩展共用max_citation_requests；响应最多2MB，限流保留Retry-After并暂停服务。不自动重试传输失败；超时暂停该服务，HTTP错误和身份冲突不重试。arXiv间隔>=3.1秒、其他>=1秒，成功/失败/中断回执均缓存，不用恢复产生新重试。
扩展只从新取得合规双审的FILLED、无冲突、depth=0根开始；depth=1，每父最多5新任务，DOI/arXiv/URL去重，部分方向成功保留partial，元数据不入事实图。Frontier 容量须同时容纳各案例基础任务与扩展任务；按当前上限和任务数核对余量，不另维护固定案例数推算。

## 状态、导出与兼容

adapter是唯一状态所有者，SOCM/Frontier/EvidenceGraph/calibration由已提交事实派生；`searchos_adapter.py repair <workspace>` 重建视图，不从视图补事实。single_runner排它、adapter锁保护写入；原版SearchSession/Orchestrator不得写同一workspace。
审计及失败事件在锁内原子写入事实，不单独重建SOCM或strategy patterns；来源/候选等事实变更才更新投影。调度与导出按需读取事实，失败内容仍用于原有查询上下文与字段诊断，不依赖日志刷新视图。
模型/搜索工厂、设置解析和隔离执行器复用SearchOS；不另造后端或写回共享JSON。依赖固定于项目锁与源码修订，升级先验证实际调用边界，不迁移旧事实。
执行基线覆盖scripts/config/assets，文档基线覆盖references/SKILL/CHANGELOG；仅文档变化可警告，执行文件变化须新workspace或原归档skill，禁止补造历史基线。

当前调度接口`online_policy.decide`从同一快照返回executable_actions、各动作及汇总blocked_reasons、terminal_reason和stop_evidence；预算结果由runner传入，并保留请求前的原子预算检查。原因代码限于代码实际分支（前置未满足、待汇总、范围外、被占用、来源处理完毕/不可用、服务不可用及预算耗尽），不另持久化动作计划。无可执行动作不得伪报预算耗尽；仍有待处理来源但全部阻塞时记录error/no_executable_action，不宣称范围耗尽。
`claimed_tasks`为task_id到owner/started_at的唯一占用映射；恢复只释放对应失效invocation的占用，重试与断点仍读既有调用/assessment记录，不写invocation.active_task。旧列表格式仅兼容读取，旧基线不能直接续跑。record-gap仍接受missing/hard_cell输入，存储只保留investigate、理由及尝试；hard_cell不再投影成证据资格状态，investigate=false只限制该工作区调查范围。
多个已通过候选按report_id/candidate_index保留，不按value字符串合并；字段保留UNCERTAIN展示待汇总且不排入反复抽取，其他可调查字段继续。汇总选择接口尚未实现，不自动评审；pending_aggregation仅为案例导出的派生候选列表。中断来源只接受宿主经asyncio取消消息显式传入的StopRequest(initiator, reason, request_ref)：例如实际用户停止指令对应`task.cancel(StopRequest("user", "停止原因", "用户指令引用"))`。initiator限user/agent/system，理由及依据引用必填；这是调用方声明，不是异常类型证明的身份或授权。仅显式user映射user_aborted，agent/system或无来源的KeyboardInterrupt/CancelledError映射error/execution_interrupted；无来源记unknown，不解析自由文本猜测。CLI裸信号没有来源信息，因此保留unknown；宿主集成须在实际停止时提供声明，不在启动配置中预填。来源与原异常类型写入已有stop_evidence和失败事件，不另建停止请求账本；历史回执不改写，恢复不继承前笔取消来源或授权。

calibration 仅在 checkpoint、最终停止或显式导出时生成；每批继续到有据停止，最终保留未完成状态。导出从事实重算并验证批次，仅回填 checkpoint 计数，不重写 schema 或 SOCM；缺失/过期 SOCM 由上述 repair 入口重建。`scripts/export_batch.py <workspace>` 重新导出已复核事实，渲染/校验入口用各脚本`--help`；不能反写事实。详细停止与四视图一致性见批次契约。
calibration不建生产库或正式cases；已有SQLite用只读URI执行queries.sql。production写入/阶段转换另行授权，保留来源外键、单位、两来源和事务校验；建库辅助入口已归档，使用前在独立副本恢复。

## 框架参考与复用边界

修改对应组件时查阅下表；框架名称不代表其全部能力已接入。以下依据本机源码核对，属于实现参考，不要求在线运行时读取这些仓库或新增依赖。

| 框架 | 可复用的可靠性设计（源码入口） | quantum-scout 的接入边界 |
|---|---|---|
| SearchOS | `socm/workspace.py`：状态校验、加锁与原子写入 | 已复用模型/搜索工厂、设置及工作区能力；领域事实由 adapter 所有，不接入第二个状态写入者。 |
| ContextGem | `internal/llm_output_structs/concept_structs.py`、`internal/base/llms.py`：引用句 ID 映射；文档序列化 | 已用于抽取和引用句映射，本地另以 source_quote_id 还原所选原文证据；序列化模型不保存完整成本统计，不能替代调用账本。 |
| DeepDive（Socialpranker） | `scripts/build_sources_csv.py`：来源文件生成派生表；`scripts/validate_phases.py`：产物契约检查 | 事实与派生导出已由本地 `export_batch` 实现；普通日志不再触发投影重建，不引入另一套阶段目录。文件存在不等于语义通过。 |
| ASReview | `asreview/database/database.py`：record_id 绑定、待标注/决策/排名分离及变更记录 | 状态分离已由 grounding/attributions/reviews 与 `review_policy` 实现；拒绝保留、待审不投影、已审不重复调用。不接入其数据库或主动学习；排序不代替接受。 |
| QuantumNovelty | `skills/claims_registry/skill.py`、`skills/novelty_audit/skill.py`：数值声明与比较规则由代码审计 | 百分数边界检查、离散评分及归一已由接地门和 `coverage_policy` 执行，不移植领域不匹配的量子优势比较器；`audit_falsify/run.sh` 在所查源码中仍是占位实现。 |
| academic-research-skills | `scripts/claim_audit_pipeline.py`、`claim_audit_finalizer.py`：结构校验、上下文绑定及确定性裁决汇总 | 上下文绑定已由 `review_policy` 实现，裁决汇总及停止由 `coverage_policy`/`online_policy` 执行；保留按案例/表/版本/分段恢复，不移植另一套缓存。 |
| scientific-agent-skills | `skills/peer-review/scripts/validate_claim_evidence.py`：claim_id/evidence_ids 关联、支持状态一致性校验 | 原始语义评审使用保存的原文片段ID，并核验请求哈希与引用绑定；结构校验仍不代表语义真实。 |

当前实现：抽取与原始语义评审按 source_quote_id 还原所选原文证据；语义评审在同一次请求输出发现理由，不执行事后重选和独立保真。守卫见[原文证据绑定](evidence.md#原文证据绑定)；离线通过不等于真实语义效果已验证。

## 代码、模型与持久化的职责

整个 skill 以“偏离后是否仍支持同一个结论”区分规则；以下分层用于设计审查，不新增运行时层级、策略引擎、状态或平行账本。搜索、正文、抽取、双审、准入、评分、导出和维护均遵循同一职责边界。

| 边界 | 权威与处理 | 放宽路径 |
|---|---|---|
| 不变量（L1） | 接地及不可变绑定、归属/语义双审、失败候选不晋升、缺证不补脑、预算与授权、纳入可追溯。证据定义在evidence；执行检查在grounding/review_policy。 | 不能靠置信度降低换取接受。新增须有真实污染或可复现反例说明放宽使结论失效；不等待线上事故。 |
| 默认策略（L2） | 来源/任务顺序、preferred_track、批次大小和搜索范围等影响覆盖与成本；online配置及workspace快照唯一生效。 | 在新invocation前选择策略并记录原因、范围与预期影响；配置变化用新workspace，既有授权不自动扩大。没有实际需求不新增开关。 |
| 诊断信息（L3） | 隔离原因、失败分类、FILLED数、抽样指标及策略偏离写入原生事件/回执；统计和视图由事实派生。 | 无需新增运行状态，不凭数量、标签或警告自动接受、阻断、重试。真正的源不可用、契约非法或预算事件仍按其决策后果处理。 |

Track四项全true、双审职责、评分有效维数与纳入阈值属于结论定义，不因存放在配置文件就成为可随意放宽的默认策略。探索可保留unknown继续调查；未知、遗漏、拒绝均不能投影为已接受。八字段的显式缺证理由可以满足既有调度记录要求，但不是覆盖证据。置信度只表达证据有限，不能补偿已知不成立。

| 职责 | 单一所有者 | 消费者与边界 |
|---|---|---|
| 来源获取与服务可用性 | searchos_network / citation_backends；online保存尝试及响应 | runner消费成功、失败、预算结果；不以失败次数猜测证据真假，按既有重试上限执行。 |
| 候选接地与接受 | grounding校验原文；review_policy.review_accepted组合绑定双审、来源可复核与身份许可 | adapter投影、coverage导出、online统计调用同一组合规则；模型仍负责语义，代码不推断限定或矛盾。多个通过评审的候选只标记待汇总，不按文字异同推断冲突或共识。 |
| 事实与任务 | adapter拥有quantum_adapter.json并派生SOCM、图和frontier | online_policy.decide统一组合领域前置、来源进度、范围和占用；runner消费可执行动作，Frontier显示同源action_plan，不反向参与调度。拒绝及待汇总记录保留。 |
| 覆盖及纳入 | coverage_policy统一缺口与覆盖见证，tracks快照定义准入与评分 | online停止、自检和导出消费同一规则；已通过准入但评分不足仍缺证，不反改准入，不把补满维度当必须耗尽预算的目标。 |
| 整笔停止 | online_policy判覆盖/操作范围；runner判预算、取消、服务和契约异常 | 候选拒绝不等于整笔失败；正常完成、取消和中断分别保留。特殊验证的人工语义止损由该笔授权规定，不伪装成通用自动语义检测。 |
| 校验、统计与展示 | export/render/validate消费事实与共享判据 | 输入契约校验、离线批次校验仍是各自信任边界的必要检查；不为消除代码重复而删除。不新增独立事实源。 |

节约与防膨胀要求：

- 确定性计算留在代码，原文/版本/位置先持久化再按ID引用；模型负责归属和语义。长度、完整句、ID、schema、非空列表、自检及FILLED各有有限含义，都不能保证语义正确；证据已识别仍漏列时，不再默认追加目录或格式补丁，也不删除暴露错误的输出。
- 保留证据与双审前提下减少调用和输入，先用保存请求离线量化；字符变化不是token或费用估计，不为诊断新增付费阶段或纠错。相同模型额外调用不保证误差独立，输入缩短不证明过载，统一表示不证明发现完整。后续方案须有不同的失效机制假设、可证伪的结果和独立止损，不能自动进入下一轮修补。
- 新边界按上述分层判断责任与决策后果；状态不设数量硬上限。每次优化明确替代/删除的旧决策来源，权威定义只维护一处；状态收敛遵循下节，不新增协调器或平行账本。
- 恢复从事实重建，不从视图补证；没有新证据不重发已失败评审。离线比较接受/拒绝、调度、导出与停止结果，只证明对应行为；真实验证须独立授权，维护完成不等于语义修复或获准续跑。

### 状态收敛约束

以下为设计约束；实际接口及兼容边界见“状态、导出与兼容”，具体实施验证状态只记项目回执。

- **决策接口归一，事实不复制。** 从同一事实快照按需计算可执行动作、各动作的阻塞原因及整笔终止原因；预算、证据资格、来源进度各自负责判据。Frontier及阻塞列表只消费该结果，不另判可执行性，不持久化第二套可执行性账本。
- **阻塞与终止分开。** 阻塞原因使用有限代码，优先复用已有原因，允许同一动作有多个原因；自由文本仅解释。终止原因独立明确，不能把取消、预算耗尽或执行中断解释成没有待办，也不把原因代码各自变成新运行状态。
- **拆分职责，同源派生。** 证据资格与当前调查范围分别由同一事实快照计算，不相互代替或各自维护；已接受且无需继续调查是合法组合。占用只保留一个权威事实，恢复所需占用者、开始时间、尝试和中断位置须可从它及原有调用/进度记录取得，不复制这些记录。
- **派生信息须有实际消费者。** 决策、人工审阅和导出都是消费者；没有消费者的派生状态不维护，仅供诊断的信息不触发调度分支或投影重建。删除前核对消费者，原始失败与审计事实保留。
- **多候选不由字符串裁决。** 不同文字不自动生成语义冲突，相同文字也不代替候选接地与双审；多个独立候选保留原文、判断及待汇总信息，汇总依据明确前不形成字段结论。汇总职责另行明确，不自动增加模型调用，不新增关键词等价或冲突规则。

合并状态前检查是否改变接受、可执行动作、恢复位置或授权成本；以下区别须保留在权威事实或可追溯原因中，不要求各自新增枚举：

| 必须区分 | 决策后果 |
|---|---|
| 待审 / 拒绝 | 尚无判断与已有否定判断不能互换，均不冒充接受 |
| 来源失败 / 未尝试 | 已消耗尝试、恢复位置及重试资格不同 |
| 预算耗尽 / 正常完成 | 授权成本与终止含义不同 |
| 用户取消 / 执行中断 | 用户意图与恢复依据不同；异常类型本身不证明用户取消 |

实施若必须压平上述区别或新增第二套持久化，停止该项并单独说明设计冲突；不就地扩权，不扩展成新一轮全局审计。

## 修改与验证

专项验证的授权、验收范围和止损记录在同笔回执；达到止损即停止该方案，不因维护、重构或离线通过自动恢复。当前任务与历史结果由AGENTS/README及CHANGELOG维护，不把每笔失败堆积为新的全局规则。

保留实际执行所需的模块依赖；`schema_generator.py` 直接读取证据协议的八字段表，不得移走或改坏该表结构。

修改组件后按上述职责规则收敛已知约束、只跑相关回归，再用获准预算重跑真实链路。离线用例可用替身，但不能冒充真实模型或真人抽查；覆盖率数字不设执行门槛。本项目测试须在沙箱外执行（Codex 使用 `sandbox_permissions=require_escalated`，遵循执行审批），避免已观察到的沙箱内异步等待卡住；不得将沙箱内挂起判为代码测试失败。使用项目解释器，例如：

```sh
PYTHONPATH=skill/scripts:skill/tests .venv/bin/python -m pytest -o pythonpath=src skill/tests -q
```

`tests/test_workflow_contracts.py` 是集成回归；其余活跃测试仅保留在线夹具、ContextGem映射、单次锚点评审与归属上下文回归。历史文档、其余测试和独立诊断工具已移入 `archive/`，不在默认阅读、测试或运行路径中；需要时先恢复到独立副本并核对依赖。

每轮只交代实际动作、预算、阻塞点、修复/重跑结果和下一步唯一动作。原始请求/响应与失败回执仍由原生运行日志保存，不另建平行分析体系。归档不改变历史 workspace；基线兼容规则见[状态、导出与兼容](#状态导出与兼容)。
