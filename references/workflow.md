# 执行流程

领域与证据规则见 [evidence.md](evidence.md)，输出与停止契约见 [batch-schema.md](batch-schema.md)。配置阈值来自 workspace 快照，不能为跑通放宽。

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

示例不是付费授权。24次只允许部分校准：八字段全为新证据的理想下界17次；一条 Track 准入拒绝约26次、通过后最少有效评分约35–37次；两条 Track 全部27单元约59次。分段、纠错及失败会增加消耗，不保证在上限内完成，不自动增加预算。

从项目根运行，`--workspace` 每次使用明确的新路径：

```sh
.venv/bin/python skill/scripts/searchos_online.py doctor --config <任务.json> --env-file <本地.env>
.venv/bin/python skill/scripts/searchos_online.py open-source --config <任务.json> --env-file <本地.env> --workspace <全新workspace> --url <正文URL> --case-id SYNC-0001
.venv/bin/python skill/scripts/searchos_online.py run --config <任务.json> --env-file <本地.env> --workspace <全新workspace>
```

`doctor` 不联网；ready 只证明本地构造检查通过。`open-source` 不经搜索，仍执行完整抽取/双审/导出；可显式传 `--expected-title`，不自动取标题。`run` 会真实搜索并使用模型额度。
正文打开仅ConnectError可在同一笔内等1秒后自动重试一次；每来源累计最多2次尝试，与显式恢复共用上限，重试前持久化失败/尝试事件并重查原时间预算。429、超时及其他错误不走此重试，模型SDK重试仍为0。固定URL最终打开失败以error/source_unavailable停止，保留实际error_type，不误记预算耗尽。
固定URL全部可执行分段已处理而仍缺证时，以operational_pool_exhausted停止，举证仅限本次固定来源/案例和禁止搜索的操作范围；不写成预算耗尽或全局耗尽，不自动重抽已处理分段。

省略模型/轮次/时间时实现默认64次/5轮/1200秒，单操作60秒；这不是默认授权。模型与ContextGem的每个实际请求、纠错、退路均计预算，SDK重试0、输出最多4096 token；格式与反证接地共用一次纠错。
总调用/时间按 invocation；正文来源上限、来源/查询恢复配额及引用HTTP按 workspace累计。预算不从 scope phase自动继承。遇429/超时停止该服务，后续恢复须有单独授权；不能沿用剩余额度自行重跑。

## 来源与调度

先处理未尝试的相关正文和未完成分段，再执行种子和从已打开来源/字段缺口派生的查询。layer1→2→3 是操作者策略，事件可供核对，不代表代码强制。失败请求不是零新增；来源数不等于案例数。
一份正文可支持多个案例，按具体任务、参与方/威胁模型、物理约束去重；不能因同作者、同物理机制或被根论文引用就继承归属。镜像/预印本/发表版不算独立来源。

正文下载保留原件、版本、提取模式及哈希。Poppler默认 reading order 不保证所有PDF正确；双栏/表格/公式/稀疏列有疑问时核对同版本页图。只读格式归一以接地门白名单为准，不放行OCR或语义改写。
发现时可合并官方arXiv abs/pdf等别名；显式版本URL打开不能被另版本缓存替代。不同DOI或未识别镜像不凭标题猜测同文。身份请求按完整版本缓存。

抽取使用ContextGem原生JSON数组格式，不要求服务端JSON Schema或maxLength支持。发送前按句列出≤50字符的连续原文片段及本轮ID，模型在value.source_quote_id中选ID，客户端按ID取回原文；不自由生成短引、不截写既有引文、不自动换ID或引用句。完整原响应先保存，选择展开后经本地Candidate逐项校验；未知ID或非法项单独拒绝并保留原值，其他合规项继续，不增加请求或纠错。

每次最多8候选；先Candidate契约，再ContextGem引用句唯一映射，再接地，之后逐候选归属/语义双审，成功才投影。部分非法候选隔离并保留原值/错误/调用ID；全违规停止error/contract_violation，空抽取不是违规。句子映射失败不触发服务退路，不靠全文搜索换引用句或任取首个匹配。
ContextGem发送前将句子视图中的空白归一为空格，避免其提示清洗先删换行造成粘词；保存的正文、分句边界和接地原件不变。反证短引超长且原引文均已接地，或判断结构合规但短引在有效原位置不存在时，共享的一次纠错从预先生成的连续原文短片段中选择option_id，不再生成引文或自由词序号。候选逐项满足1–50字符并保留原始空白；超长原引文仅提供其已接地范围内的词边界子片段，非原文引文仅使用原有效位置的片段。程序列举候选不作语义选择；仅筛除纯英文代词/功能词或不含字母的孤立数字/符号片段；正文中显式百分数的比较符、数字及百分号须作为连续整体保留，不能从中切开（当前只覆盖%、％、‰，不是通用单位解析），且已接地超长引文的子片段须保留原引文全部显式英文否定标记（含次数）。这是保守词法筛选，不能验证否定作用域或语义；非原文历史短引不提供强制标记。无合格选项仍拒绝，不增纠错；模型选定后仍须同一反证语义复核。未列出的ID、空候选列表、超长或未接地结果均拒绝，不自动截短、换ID或再纠错。完整选择数组可无损包入selections对象；原响应保留。路径必须一一绑定，其他判断/反证/位置原样保留，合并后重新校验完整结构和接地。
同来源跨表不共享游标；抽取缓存绑定案例/表/来源版本/分段/字段范围。已获有效归属但缺语义只补语义；已完成双审不重复调用。仅匹配范围的全文处理结束才标done，异常保留本批起点。

## 准入、评分、抽取

先建立八字段问题定义。只有有证据的值或原始 record-gap 的非空 reason 才计审计完整；默认reason和单篇无候选不补齐完成度。关键场景字段无证据不得入Track；研究部署本身不是拒绝理由。

两条Track独立判断四项准入，全部true才调度该Track评分。有证据的false可完成拒绝分支；insufficient_evidence不是false。评分不足只能令评分为null/失败，不能回改已通过的准入。
每维分数只为1/3/5/null；有效维数n，原始分为有效维之和，归一分=`score_total/(n*5)*25`。NLC至少4/5有效维、安全至少5/6；当前归一门槛15，实际使用配置快照值。NLC原始上限25、安全30，两者归一上限均25。
至少一条Track准入通过且达到分数门槛才计纳入；另一Track保留自身结论。display_track只控制展示，不能改变评估、来源或计数。

failure_class 保持：insufficient_evidence、failed_admission、classical_infrastructure、not_a_real_world_problem、not_modelable_as_nonlocal_game、classical_workaround_exists、problem_definition_incomplete、not_an_application_case；解释时同时读取passed_admission。

## 引用身份与扩展

默认关闭。`citation_identity.enabled` 允许 crossref/arxiv/semantic_scholar/openalex；`citation_expansion_backend` 独立选择 none/openalex/semantic_scholar。旧citation_backend仍兼容，但不能与新allowlist重复配置。S2 key可选，匿名429不是缺key；本适配器的OpenAlex需OPENALEX_API_KEY。
DOI优先已启用Crossref，arXiv优先已启用arXiv；按需S2/OpenAlex补充，无标识不请求、不按标题搜索。Crossref404=unknown，不证明论文不存在。标题相似度>=0.70只是元数据启发式，正文资格独立核查。
verified要求标识/版本与expected_title一致；缺标识/标题/版本核验或访问受限为unknown；任一mismatch或跨服务标题冲突优先，拦截相关来源候选。unknown不降低正文资格；关闭时不伪造服务失败。多服务全verified与partial分别报告，未调用服务不补造回执。
每HTTP先持久占预算，身份/扩展共用max_citation_requests；响应最多2MB，限流保留Retry-After并暂停服务。实现有最多一次传输恢复能力，但不授权自动续试；HTTP错误和身份冲突不重试。arXiv间隔>=3.1秒、其他>=1秒，成功/失败/中断回执均缓存，不用恢复产生新重试。
扩展只从新取得合规双审的FILLED、无冲突、depth=0根开始；depth=1，每父最多5新任务，DOI/arXiv/URL去重，部分方向成功保留partial，元数据不入事实图。Frontier上限200，每案例5基础任务，40案例已无扩展余量。

## 状态、导出与兼容

adapter是唯一状态所有者，SOCM/Frontier/EvidenceGraph/calibration由已提交事实派生；`searchos_adapter.py repair <workspace>` 重建视图，不从视图补事实。single_runner排它、adapter锁保护写入；原版SearchSession/Orchestrator不得写同一workspace。
模型/搜索工厂、设置解析和隔离执行器复用SearchOS；不另造后端或写回共享JSON。依赖固定于项目锁与源码修订，升级先验证实际调用边界，不迁移旧事实。
执行基线覆盖scripts/config/assets，文档基线覆盖references/SKILL/CHANGELOG；仅文档变化可警告，执行文件变化须新workspace或原归档skill，禁止补造历史基线。

每批写checkpoint/comparison并继续到有据停止，最终也保留未完成状态。`scripts/export_batch.py <workspace>` 重新导出已复核事实，渲染/校验入口用各脚本`--help`；不能反写事实。详细停止与四视图一致性见批次契约。
calibration不建生产库或正式cases；已有SQLite用只读URI执行queries.sql。production写入/阶段转换另行授权，保留来源外键、单位、两来源和事务校验；建库辅助入口已归档，使用前在独立副本恢复。

字段归属/语义仍需模型实质判断；机器守卫只验证绑定/结构/接地。原始模型响应与失败保留，USD无回执为unknown；same_model_used如实记录，不把模型角色拆分当误差独立。
反证的范围选择通过结构与接地后，另一次模型请求复核所选片段是否支持同一原反证；该请求计入semantic预算、不得格式纠错，非supported或绑定不完整即拒绝整项判断。复核必须以selected_quote原样回传实际replacement短引（包括空白），逐字核对，不能用被拒绝的原引文代替；孤立代词缺少实质反证时应为unclear。OpenAI兼容传输仅对该请求启用原生JSON模式并记录response_format，不修改共享设置；仍校验完整响应，说明加JSON不截取、不重试。此复核不改变原反证flag或原结论，也不保证模型判断无误。
