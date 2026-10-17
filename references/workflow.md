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

示例不是付费授权。预算按实际 extraction、attribution、semantic 和其他请求累计；纠错及保真请求均计入对应类别，不另维护固定调用下界。以原生调用账本判断消耗，上限不保证完成。

从项目根运行，`--workspace` 每次使用明确的新路径：

```sh
.venv/bin/python skill/scripts/searchos_online.py doctor --config <任务.json> --env-file <本地.env>
.venv/bin/python skill/scripts/searchos_online.py open-source --config <任务.json> --env-file <本地.env> --workspace <全新workspace> --url <正文URL> --case-id SYNC-0001
.venv/bin/python skill/scripts/searchos_online.py run --config <任务.json> --env-file <本地.env> --workspace <全新workspace>
```

`doctor` 不联网；ready 只证明本地构造检查通过。`open-source` 不经搜索，仍执行完整抽取/双审/导出；可显式传 `--expected-title`，不自动取标题。`run` 会真实搜索并使用模型额度。
### 预算与失败处理

省略模型/轮次/时间时实现默认64次/5轮/1200秒，单操作60秒，输出最多4096 token；默认值不是授权。调用与时间按 invocation，正文来源上限、来源/查询恢复配额及引用 HTTP 按 workspace 累计；不从 scope phase 自动继承。实际请求计数见上文账本，模型 SDK 重试为0，格式纠错见[证据协议](evidence.md#短引纠错)。

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

抽取使用ContextGem原生JSON数组格式，不要求服务端JSON Schema或maxLength支持。发送前按句列出≤50字符的连续原文片段及本轮ID，模型在value.source_quote_id中选ID，客户端按ID取回原文；不自由生成短引、不截写既有引文、不自动换ID或引用句。完整原响应先保存，选项目录随请求落盘并校验哈希后读取，选择展开后经本地Candidate逐项校验；未知ID或非法项单独拒绝并保留原值，其他合规项继续，不增加请求或纠错。

ContextGem 服务不可用时，原生退路复用相同片段切分器和 source_quote_id 契约，程序从保存目录恢复短引及位置；未知 ID、回传文字或位置覆盖均隔离拒绝，仍须接地与双审。

每次最多8候选；先Candidate契约，再ContextGem引用句唯一映射，再接地，之后逐候选归属/语义双审，成功才投影。部分非法候选隔离并保留原值/错误/调用ID；全违规停止error/contract_violation，空抽取不是违规。句子映射失败不触发服务退路，不靠全文搜索换引用句或任取首个匹配。
ContextGem发送前的空白处理及反证短引纠错统一见[证据协议](evidence.md#短引纠错)。
同来源跨表不共享游标；抽取缓存绑定案例/表/来源版本/分段/字段范围。已获有效归属但缺语义只补语义；已完成双审不重复调用。仅匹配范围的全文处理结束才标done，异常保留本批起点。

## 评估调度

依次执行八字段问题定义、Track 准入和通过准入后的评分；前置门、缺证处理和部分评分见[准入与评分](evidence.md#准入与评分)，具体字段见[问题定义](evidence.md#问题定义)。停止时按[案例覆盖契约](batch-schema.md#案例覆盖与在线导出)逐案例重算，不跨案例或 Track 拼接。

## 引用身份与扩展

默认关闭。`citation_identity.enabled` 允许 crossref/arxiv/semantic_scholar/openalex；`citation_expansion_backend` 独立选择 none/openalex/semantic_scholar。旧citation_backend仍兼容，但不能与新allowlist重复配置。S2 key可选，匿名429不是缺key；本适配器的OpenAlex需OPENALEX_API_KEY。
DOI优先已启用Crossref，arXiv优先已启用arXiv；按需S2/OpenAlex补充，无标识不请求、不按标题搜索。Crossref404=unknown，不证明论文不存在。标题相似度>=0.70只是元数据启发式，正文资格独立核查。
verified要求标识/版本与expected_title一致；缺标识/标题/版本核验或访问受限为unknown；任一mismatch或跨服务标题冲突优先，拦截相关来源候选。unknown不降低正文资格；关闭时不伪造服务失败。多服务全verified与partial分别报告，未调用服务不补造回执。
每HTTP先持久占预算，身份/扩展共用max_citation_requests；响应最多2MB，限流保留Retry-After并暂停服务。实现有最多一次传输恢复能力，但不授权自动续试；HTTP错误和身份冲突不重试。arXiv间隔>=3.1秒、其他>=1秒，成功/失败/中断回执均缓存，不用恢复产生新重试。
扩展只从新取得合规双审的FILLED、无冲突、depth=0根开始；depth=1，每父最多5新任务，DOI/arXiv/URL去重，部分方向成功保留partial，元数据不入事实图。Frontier 容量须同时容纳各案例基础任务与扩展任务；按当前上限和任务数核对余量，不另维护固定案例数推算。

## 状态、导出与兼容

adapter是唯一状态所有者，SOCM/Frontier/EvidenceGraph/calibration由已提交事实派生；`searchos_adapter.py repair <workspace>` 重建视图，不从视图补事实。single_runner排它、adapter锁保护写入；原版SearchSession/Orchestrator不得写同一workspace。
普通审计事件在锁内原子写入事实，不重建 SOCM；失败事件因影响调度策略仍重建投影。调度与导出从事实重算，不能依赖日志触发派生视图刷新。
模型/搜索工厂、设置解析和隔离执行器复用SearchOS；不另造后端或写回共享JSON。依赖固定于项目锁与源码修订，升级先验证实际调用边界，不迁移旧事实。
执行基线覆盖scripts/config/assets，文档基线覆盖references/SKILL/CHANGELOG；仅文档变化可警告，执行文件变化须新workspace或原归档skill，禁止补造历史基线。

calibration 仅在 checkpoint、最终停止或显式导出时生成；每批继续到有据停止，最终保留未完成状态。导出从事实重算并验证批次，仅回填 checkpoint 计数，不重写 schema 或 SOCM；缺失/过期 SOCM 由上述 repair 入口重建。`scripts/export_batch.py <workspace>` 重新导出已复核事实，渲染/校验入口用各脚本`--help`；不能反写事实。详细停止与四视图一致性见批次契约。
calibration不建生产库或正式cases；已有SQLite用只读URI执行queries.sql。production写入/阶段转换另行授权，保留来源外键、单位、两来源和事务校验；建库辅助入口已归档，使用前在独立副本恢复。

## 框架参考与复用边界

修改对应组件时查阅下表；框架名称不代表其全部能力已接入。以下依据本机源码核对，属于实现参考，不要求在线运行时读取这些仓库或新增依赖。

| 框架 | 可复用的可靠性设计（源码入口） | quantum-scout 的接入边界 |
|---|---|---|
| SearchOS | `socm/workspace.py`：状态校验、加锁与原子写入 | 已复用模型/搜索工厂、设置及工作区能力；领域事实由 adapter 所有，不接入第二个状态写入者。 |
| ContextGem | `internal/llm_output_structs/concept_structs.py`、`internal/base/llms.py`：引用句 ID 映射；文档序列化 | 已用于抽取和引用句映射，本地另以 source_quote_id 还原短引；序列化模型不保存完整成本统计，不能替代调用账本。 |
| DeepDive（Socialpranker） | `scripts/build_sources_csv.py`：来源文件生成派生表；`scripts/validate_phases.py`：产物契约检查 | 事实与派生导出已由本地 `export_batch` 实现；普通日志不再触发投影重建，不引入另一套阶段目录。文件存在不等于语义通过。 |
| ASReview | `asreview/database/database.py`：record_id 绑定、待标注/决策/排名分离及变更记录 | 状态分离已由 grounding/attributions/reviews 与 `review_policy` 实现；拒绝保留、待审不投影、已审不重复调用。不接入其数据库或主动学习；排序不代替接受。 |
| QuantumNovelty | `skills/claims_registry/skill.py`、`skills/novelty_audit/skill.py`：数值声明与比较规则由代码审计 | 百分数边界检查、离散评分及归一已由接地门和 `coverage_policy` 执行，不移植领域不匹配的量子优势比较器；`audit_falsify/run.sh` 在所查源码中仍是占位实现。 |
| academic-research-skills | `scripts/claim_audit_pipeline.py`、`claim_audit_finalizer.py`：结构校验、上下文绑定及确定性裁决汇总 | 上下文绑定已由 `review_policy` 实现，裁决汇总及停止由 `coverage_policy`/`online_policy` 执行；保留按案例/表/版本/分段恢复，不移植另一套缓存。 |
| scientific-agent-skills | `skills/peer-review/scripts/validate_claim_evidence.py`：claim_id/evidence_ids 关联、支持状态一致性校验 | 保真复核已采用 ID/支持判断契约，并补充保存请求哈希与引用完整性校验；结构校验仍不代表语义真实。 |

当前实现：抽取按 source_quote_id 取回短引；反证选择从已保存目录解析 option_id，保真复核仅返回 quote_id/support/reason，客户端校验请求哈希及 ID 完整性。具体守卫只在[短引纠错](evidence.md#短引纠错)定义；实现和离线检查不等于真实语义效果已验证。

## 代码、模型与持久化的职责

- 类型、长度、标识绑定、来源哈希、算分、预算和停止条件等确定性规则由代码执行；文档引用同一实现，不要求模型重复计算或抄写不可变字段。
- 原文、短引、位置及版本先持久化，再以绑定具体请求和证据对象的 ID 供模型引用；程序从已保存记录还原文字。未知、重复、缺失、错配或被篡改的引用必须拒绝，不自动猜配或改写。
- 模型负责归属、语义支持、领域条件及反证判断，输出绑定 ID 的结论与理由；代码不能把字符串匹配或 ID 有效冒充语义成立。
- 落盘保留候选、待复核、接受与拒绝的区别及原始请求响应；只有满足既有证据守卫才能投影为可用事实。恢复从事实记录重建，不从派生视图补事实，也不自动重发付费请求。
- 优先复用现有事实源、契约和校验函数；消除重复定义，不为下沉新增并行账本、缓存层或配置开关。行为改变须验证拒绝路径、证据完整性与恢复，离线通过不等于真实验证。

## 修改与验证

保留实际执行所需的模块依赖；`schema_generator.py` 直接读取证据协议的八字段表，不得移走或改坏该表结构。

修改组件后只跑相关回归，再用获准预算重跑真实链路。离线用例可用替身，但不能冒充真实模型或真人抽查；覆盖率数字不设执行门槛。本项目测试须在沙箱外执行（Codex 使用 `sandbox_permissions=require_escalated`，遵循执行审批），避免已观察到的沙箱内异步等待卡住；不得将沙箱内挂起判为代码测试失败。使用项目解释器，例如：

```sh
PYTHONPATH=skill/scripts:skill/tests .venv/bin/python -m pytest -o pythonpath=src skill/tests -q
```

`tests/test_workflow_contracts.py` 是集成回归；其余活跃测试仅保留在线夹具、ContextGem映射、短引纠错与归属上下文回归。历史文档、其余测试和独立诊断工具已移入 `archive/`，不在默认阅读、测试或运行路径中；需要时先恢复到独立副本并核对依赖。

每轮只交代实际动作、预算、阻塞点、修复/重跑结果和下一步唯一动作。原始请求/响应与失败回执仍由原生运行日志保存，不另建平行分析体系。归档不改变历史 workspace；基线兼容规则见[状态、导出与兼容](#状态导出与兼容)。
