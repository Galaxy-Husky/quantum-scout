# Pilot 工程门禁与真实服务验证

本文件维护改进优先级、两级验收与运行期记录；测试保障边界见 [testing.md](testing.md)。
它不改变证据资格、停止守卫、置信度规则或 production 边界，不自动启动 Pilot。

## 两级验收

| 类别 | 验收条件 | 未满足时 |
|---|---|---|
| 离线工程门禁（P1） | 列明的契约用例全部通过；失败与跳过逐项说明 | 阻塞 Pilot 启动 |
| 真实服务验证（条件项） | 有明确凭据、请求/时间预算时验证真实搜索、引用、文档全链路 | 标为“未验证”并披露风险；不阻塞 Pilot |

离线通过只表示已列测试通过，不等于代码全覆盖、语义正确或整体可直接上线。
真实服务项独立列出已验证、未验证或实测失败及回执；不得混入离线通过率。
真实失败不能改写成“未验证”或空结果。Pilot 启动仍需明确阶段指令及运行配置。

## 优先级与阶段

| 阶段 | 优先级 | 工作与验收 |
|---|---|---|
| 1 核心闭环 | P1 必须 | 候选契约前置、接地、归属/语义/投影绑定、冲突降级、单格填充、同案例同 Track 覆盖及准入失败分支、反证结构与范围、停止举证均有有效/无效输入回归 |
| 1 核心闭环 | P1 必须 | 中断、有限恢复、预算与来源去重；online / SOCM / batch / render 共同事实对齐；SQLite 不在此阶段 |
| 1 核心闭环 | P1 必须 | 极小预算、零/非法配置拒绝、候选上限、多 provider/backend 配置矩阵；在线 CLI 配置错误退出 2 且不创建 workspace |
| 1 核心闭环 | P1 必须 | 全部合法停止值、警告类别、多 Track 分数、人工状态在报告/适用的单案例草稿中如实展示；合成人工导入不改停止快照 |
| 1 核心闭环 | P1 必须 | 真实 PDF/HTML 解析引擎处理本地合成文档并接地；这不等于真实文档/模型全链路已验证 |
| 2 工程增强 | P2 | 文档/模型/网络故障与部分成功；可检测异常拒绝或留有降级事件，恢复不重复已完成动作 |
| 2 工程增强 | P2 | 20+ 页、5+ 案例、10+ 来源合成资源基准；置信度分布保留 low/medium，不增加门槛 |
| 2 工程增强 | P2 | 10+ workspace 快照去重、排序、窗口与损坏跳过；同 workspace 只算一次观察 |
| 3 Pilot 评估 | — | 核对 P1、独立标注真实服务状态、披露语义/反证残留风险，给出工程可行性结论 |
| 4 运行期 | P3 | 按批次真人抽查、并发容量压测、覆盖率改善与历史只读兼容回归 |

零轮次是非法配置，预期报错，不应被当作正常停止。候选上限是 8；“超多字段”用来验证拒绝，
不改变领域字段配置。不同 provider/backend 的配置接受不能写成真实服务组合已跑通。

同 workspace 排它与锁异常释放可做低成本离线回归；生产容量压测仍属 P3。
flock 的锁文件允许保留，验收看进程退出后能重新取得锁；不要 unlink 正被使用的锁 inode。
未识别镜像、不同 DOI 不凭标题猜测同文；官方 arXiv 别名和显式正文版本边界见
[source_cache.md](source_cache.md)。

## 可复现命令

使用项目解释器，冻结 skill 后执行 [离线命令](testing.md#执行与验收)。
默认 pytest 不收集 `live_api_contracts.py` 与 `live_attribution_regression.py`。

纯离线合成资源基准（不测真实模型耗时、密集证据图或生产容量）：

```sh
<python> <skill>/tests/offline_benchmark.py --samples 3 --output <validation>/benchmark.json
```

历史批次只读兼容与当前字段引用置信度分布：

```sh
<python> <skill>/tests/historical_contracts.py <workspace> [<workspace> ...] \
  --output <validation>/historical-audit.json
```

仅阅读废弃停止值时加 `--legacy-audit`，不认可旧完成声明；不恢复执行、不迁移、不重写输入。
输出区分 passed/incompatible/unverified；passed 只表示当前渲染契约可读，不能证明历史来源或语义质量。
批次、adapter 与 checkpoint 的哈希在读取前后校验；输出必须放在输入 workspace 之外。

真实 API 探针必须显式启用，使用 SearchOS 原生搜索 provider 与引用身份实现，不调用模型。
`SERPER_API_KEY` / `TAVILY_API_KEY`、`S2_API_KEY`、`OPENALEX_API_KEY` 放在本地 dotenv（例如项目 `.env`）或进程环境；
通过 `--env-file` 加载，已有同名环境变量优先。格式也见 [环境模板](../assets/searchos.env.example)。
在线运行在 JSON 中显式配置 `citation_identity.enabled`（默认空列表）和独立的引用扩展后端；
旧单值 `citation_backend` 仍兼容。探针按每项 `backend` 选择，不自动切换后端。
Crossref/OpenAlex 使用 DOI，arXiv 使用 arXiv ID，Semantic Scholar 支持 DOI/arXiv。
实现状态名是 `mismatch`，不是 `mismatched`。

探针 JSON 使用以下结构；查询、预期标题/数量须由操作者指定，避免动态结果漂移被误报为实现错误。
这些是接口断言，不是语义金标准；配置可仅含部分 probe。

```json
{
  "probes": [
    {"kind": "search", "provider": "serper", "query": "quantum clock synchronization", "max_results": 1, "expected_count": 1},
    {"kind": "citation", "backend": "semantic_scholar", "ids": {"arxiv": "1309.3923"}, "expected_state": "unknown"}
  ]
}
```

`expected_title` 是可选的非空字符串；引用正常身份匹配用实际预期标题及 `expected_state: verified`，
错配契约用明确不匹配标题及 `mismatch`；省略标题只能检验 identifier 查询，不能声称标题核验通过。
不主动制造真实服务 429/超时，使用离线注入验证；实测遇到 429 即暂停该服务的后续探针。
输出保留请求状态、响应哈希/正文和 unknown 原因，报告不保存请求密钥。

```sh
<python> <skill>/tests/live_api_contracts.py \
  --config <probe-config.json> --env-file <local.env> --allow-live \
  --max-requests <explicit-cap> --max-seconds <explicit-seconds> --output <validation>/live-api
```

预算包含重定向请求；到限即停止，不用重试刷出通过结果。
API 探针通过仍不证明真实 PDF/HTML → 抽取 → 双审 → 导出的全链路通过。
真实模型链路使用 [在线入口](searchos-online.md) 的独立 workspace 与模型调用预算。

## 运行期每批审计模板

每批在项目 validation 目录记录，未知值写“未提供”，不能补零。来源保留 batch 路径与哈希、
skill 基线、配置摘要、workspace、invocation；人工审计记录须由真人提供，合成夹具不得入研究库。

| 指标 | 数据口径/填写内容 |
|---|---|
| 工程门禁 / 真实服务 | 测试命令和报告链接；各真实项已验证/未验证/失败及原因 |
| 运行边界 | 配置端点、查询、预算、实际停止值、stop_evidence、未处理来源/分段 |
| 字段填充率 | SOCM filled/total_cells；另报问题定义有证据字段数，勿混用分母 |
| 失败原因 | quality.field_diagnostics 的原因及覆盖字段数；原因可并存，勿相加推算失败率 |
| 置信度 | 当前有证据字段引用的 low/medium/缺标签数量，注明按字段引用计数；非独立候选数 |
| 来源分布 | 唯一来源 ID、打开状态、发现层级；层级事件数与来源数分别报告 |
| 人工审计 | 当前 human_audit_status、audited_samples/eligible_supported、覆盖率及阈值；停止时快照另列 |
| 语义偏差 | 已抽查样本的错误类型与分布；归属抽查精确率不等同所有语义正确率，不能外推总体 |
| 成本与性能 | 实测时间、内存范围、调用/token/USD；真实模型耗时未测则写“未验证” |
| 待处理 | 工程缺陷、服务可用性问题与模型残留风险分别列出、分配后续动作 |

每份报告注明“有限运行范围，不做全局证据穷尽宣称”；low/medium 均保留标签，
不自动过滤或提升权重。异常解析可能仍产出可读文本，测试不能保证发现所有乱码或部分文档损坏。
行覆盖 ≥90%、分支 ≥85% 是 P3 改善目标，必须报告实测值与未覆盖清单，不能包装成已达成。

模型输出失败归因需控制提示词、字段/上下文、模型及参数；不得从少量运行直接认定 flash 能力不足。付费实验先固定输入/参数/预算和独立 workspace，再按明确授权执行。真实评分和多案例覆盖正例必须由实际证据支持；不以预填全 true/全 5 替代真实验证。真实服务项仍为独立条件项，不自动改成 Pilot 硬门禁。


## 失败诊断与后续真实验证的顺序

付费调用只在当前任务明确授权和独立预算内执行；“执行所有优先级”不覆盖明确的不付费、
不启动 Pilot/production 或不跨基线恢复边界。限制下仍完成离线分析、配置检查和计划校验，
逐项报告 prepared_not_executed 及原因，不把准备当实测通过。

| 优先级 | 工作与实际验收 |
|---|---|
| P0 | 固定历史未核准输入、提示词、schema、参数和 skill 哈希后诊断短引失败；诊断不写事实、覆盖或 Track。既定 6×2 方案最多 12 次/900 秒、单次90秒、SDK重试0、格式纠错0；不是默认许可。先诊断再决定是否修改生产提示词、模型或50字符契约。 |
| P1 | 独立配置/workspace 验证八字段前置门、C1–C4/S1–S4 三态与准入→评分调度；全 true 才评分，有 false 不评分，insufficient_evidence 保留。门槛来自快照。真实分值由证据决定，QS 30→25 的边界计算可离线验证，不要求真实论文必须满分。 |
| P1 | 多案例逐个 coverage_witness/self_audit；只完成一个不能覆盖其余案例，configured_case_ids 顺序、case_completions 与单数别名须一致；sources_unattempted 可大于零，validate_case_coverage_stop 须通过。 |
| P1/P2 | native 引用扩展只从新取得合规双审事实的 FILLED、无冲突、depth=0 根开始；depth=1、每父最多5新任务、去重、部分成功均有回执。仅 metadata 客户端成功不能记作 native 调度通过。 |
| P1/P2 | S2 DOI/arXiv 两路径独立记录身份核验；可用已有合法 key，匿名也受支持。429 如实标 rate_limited、保留 Retry-After 并暂停后续端点；不写成缺 key/论文不存在，不自动重试 HTTP 错误。 |
| P2 | 明确反证三个 flag 防护的范围、PDF 表格/公式/稀疏列人工核对边界；覆盖率按模块与进程范围分类，不刷断言。 |
| P3 | 未提供 USD 价格回执保留 unknown；披露 same_model_used，不能把 reviewer ID 差异当误差独立。真人抽查未执行即未验证。 |

验收允许诊断在预算内未观察到差异，或因限流/超时提前终止；这都是可报告结果，不能为了
“至少一条差异”追加请求或选择性汇报。两个重复不是准确率估计或充分因果证明。
阶段进度按能力分别记录：模型诊断未执行不妨碍独立免费元数据/离线检查，但依赖新模型事实的
准入、覆盖与 native 扩展不能用合成结果或历史判定补成真实通过。不得自动续费、加预算或跨基线恢复。

冻结是实验基线要求，不是必须退回某个版本号。沿用已准备计划时保留其执行文件、输入、
schema 与参数哈希；若新版本只改文档且执行文件逐一相同，可视为同一执行基线。
在新目录运行诊断，不恢复历史 workspace，也不导入历史准入/双审结论。
“冻结”不禁止计划预先声明的条件差异；C 类字段/候选/规则组合变更不能称为单一字段变量。
只修诊断调度器的预算或停止守卫时，须保留原件、差异与哈希，不能夹带 worker 或契约修改。

分笔授权仅覆盖获准的一笔。诊断观察到差异也不自动授权 Track、覆盖或引用扩展；后续须有独立预算。
分别记录契约结果、反证 flag、引文长度与接地结果。首次响应之间的 flag 差异不等于修复时
true→false；三个 flag 全 false、列表为空而通过契约，不证明反证搜索充分或模型更优。
有引文但结构已拒绝时，额外的只读接地分析须与运行时直接拒绝原因分列，不覆盖原回执。
