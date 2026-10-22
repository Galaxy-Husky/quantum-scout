# 变更记录

## v21 — 2026-10-18 面向外部评审的探索说明

- 按用户要求将[语义方案探索与评估](docs/semantic-design-evaluation.md)纳入skill仓库，并在DESIGN-PROGRESS添加入口：独立说明37–39笔失败实例、方向1指标撤回及停止、方向2各变体与条件化17→25调用示例、方向3风险；无需访问内部回执。明确实际人/代理原文审阅与旧标注回放的区别，下一项决策是独立验收承担者及范围。
- 方向2仅核对现有单锚点/单次语义接口、保存原文偏移及历史拆分失败，未实现新原型。文档路径/内容边界与差异检查通过；未新增运行代码或测试，付费及模型调用0，真实仍第39笔6/8、语义失败、未准入/评分。结果续记原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的 subsequent_direction_assessment.direction2_feasibility。

## v21 — 2026-10-18 方向1审阅纠正并停止

- 代码审阅发现Q41仅绑定原文/旧理由后固定返回caught，不能计作独立捕获；此前11/11口径撤回，现为10项固定反例检查命中、1项仅旧标注保留。此前4→0混用旧总结分歧与新列表差异，后值改为不可比较；结构化列表仍0→0。
- 已纠正隔离原型及同一comparison.html/results.json，按反掩盖条件停止方向1（回放退出1）。10项报告/停止回归通过（0.076秒）不代表原型验收通过；未继续补语义判据或实施其他方向。
- 付费及模型调用0，37–39笔事实/导出6文件哈希不变；真实仍第39笔6/8、语义失败、未准入/评分。原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的 subsequent_direction_assessment.direction1_prototype 保留初次结果并标明已被审阅纠正；下一步仅离线重新评估方向2。

## v21 — 2026-10-18 方向1隔离原型初次记录（已被后续审阅纠正）

- `artifacts/quantum-scout/prototypes/shared-findings-20261018/` 保存独立原型、37–39笔20份已完成评审/原文夹具及单张comparison.html：解释与导出共享发现，验收另读带哈希/偏移的原文及明确agent标注，原总结保留。未改线上实现、evidence规则或汇总契约。
- 初次报告的“11/11独立捕获”和“4→0”口径已撤回，实际为10项固定反例检查命中、1项仅保留旧标注，前后总结差异不可同口径比较；以本文件上方“方向1审阅纠正并停止”为准。初次9项检查通过（0.073秒）未揭露该验收缺陷；原生事实与导出6文件哈希不变。
- 预算、付费及新增模型调用均0；初次待审阅状态已由后续停止结果替代，不选定线上方案。真实状态仍第39笔6/8、语义失败、未准入/评分；量化及命令续记原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的 subsequent_direction_assessment.direction1_prototype。

## v21 — 2026-10-18 语义方向离线归因确认

- 对照第39笔原生评审与已保存正文：inputs_and_outputs、existing_practice确认限定保留失败；success_criteria的Q123缺CHSH前件、Q124依赖Otherwise，constraints的Q41不足以支持“实现特有”理由，证据承载疑点仍在。数值强弱矛盾目标未触发；不推断模型过载或内部原因。
- 候选方向优先评估原文绑定发现的单一表示，但不得靠删除总结掩盖遗漏；锚点/支持分离须先评估既有调用预算内的跨片段绑定，缩范围及新增拆分调用暂无充分依据。仅方向比较，未改运行实现或选定上线方案；具体预算待可审阅原型量化，语义失败即停、不纠错续跑。
- 原生状态SHA256核对不变，本轮付费上限及调用均0，未运行模型测试；真实仍第39笔6/8、语义失败、未准入/评分。归因及候选比较续记原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的 subsequent_direction_assessment.attribution_confirmation_20261018，供下一步离线原型选择消费。

## v21 — 2026-10-18 单选交叉边界收尾

- 核对 d2c7aa8：拒绝候选仍可调查新来源、快照失效保留历史且不自动接受替代项、旧排除项须显式重选均已有用例；补入“旧排除候选失去双审资格后，当前快照的显式重选仍拒绝且事实不变”。隔离副本 test_aggregation.py 实测12项/9子用例通过（24.46秒），差异检查通过；未改运行代码。
- evidence.md 明确集合结论是否支持及时间待决，当前不实现；人工身份是有意的调用方声明而非认证。快速核对本次收敛相关投影、汇总、导出和归属统计均有消费者，未发现需删除的无消费者派生状态；不扩展为全范围审计。
- 预算及付费调用均0；夹具不是真人抽查或语义验证，真实状态仍第39笔6/8、语义失败、未准入/评分。结果续记 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的 state_convergence.optional_human_aggregation.boundary_followup；结构收尾完成，下一步为独立决定语义方案，真实运行另行逐笔授权。

## v21 — 2026-10-18 可选人工单选回写（离线验证）

| 变化 | 验证与限制 |
|---|---|
| 新增aggregation-context/aggregate-field：select_one、reject_all、keep_pending绑定具体候选、原文位置/哈希、双审与来源快照，决定追加到原生事实源；所选候选供投影、准入、评分及覆盖见证消费。 | 不改写双审，不拼接候选；组合结论暂不支持时显式保留待汇总原因。候选/评审/来源变化使决定失效；旧排除项须人工显式重新选择，不因新证据自动复活。 |
| 人工回写是可选能力；移除“待汇总即排除字段后续调查”的调度条件，来源游标仍阻止旧候选重复抽取/评审。 | 未形成结论的字段不支撑准入/评分，但自动搜索可在当前授权范围和预算内处理新来源，无需人工介入。 |
| 九条边界、请求绑定与无人工回写自动处理新来源的runner用例，以及调度/集成回归共54项、20子用例通过（75.56秒）；第37–39笔原始事实与接受/覆盖/停止回放不变，skill格式及差异检查通过。 | 所有候选、人工指令及模型响应均为离线夹具；不是真人抽查或语义验证。新增付费0，真实状态仍第39笔6/8、语义失败、未准入/评分；不恢复旧方案或额度。 |

结果续记原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的state_convergence.optional_human_aggregation；真实运行须另行逐笔授权。

## v21 — 2026-10-18 中断来源单项收尾（离线验证）

- 删除“KeyboardInterrupt/CancelledError即用户取消”的推断；宿主可通过既有asyncio取消消息携带StopRequest(user/agent/system、原因、实际指令引用)。仅显式user记user_aborted，其余记error及execution_interrupted来源诊断；裸信号/自由文本为unknown。保留原异常、占用释放及调用断点，不新增状态、命令、请求账本或恢复授权。
- 隔离副本实际Task.cancel、来源不继承、未知信号、崩溃恢复和预算矩阵共12项/13子用例通过（23.73秒），按哈希同步4个文件；第37–39笔原生事实与决策回放不变，格式/差异检查通过。新增付费0，真实状态仍第39笔6/8且语义失败，历史user_aborted不改写。
- 来源是宿主显式声明，不是代码证明的用户身份/授权；未验证宿主UI集成或真实在线运行。结果续记原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的state_convergence.interruption_provenance；本轮状态优化收束，不自动扩审或复验。

## v21 — 2026-10-18 调度状态收敛实施（离线验证）

| 变化 | 验证与限制 |
|---|---|
| action_plan/decide统一领域前置、来源进度、范围和占用判断；runner、独立next-task、引用基础任务、Frontier显示及停止逻辑共用结果。不再以“没有可执行动作”伪报预算耗尽，不持久化第二份动作账本。 | 固定来源正常耗尽/失败、阻塞原因、独立领取、引用扩展、预算及恢复均由离线替身验证。 |
| hard_cell输入归一为调查范围事实，字段资格不再使用该状态；claimed_tasks成为唯一占用映射，恢复沿用原尝试/游标记录。失败日志不再重建strategy patterns，删除持久化pending_attribution和failure_patterns汇总，原始失败与字段诊断保留。 | 老占用列表仅兼容读取；新代码须新workspace，不迁移或续跑历史笔次。待审与拒绝、失败与未尝试仍分别保留。 |
| 文字不同不自动生成CONFLICT，文字相同不合并候选；多个通过候选保留待汇总及完整证据，不形成字段结论或重复抽取该字段。 | 新增pending_aggregation仅为派生导出；尚未实现汇总选择接口，无新增模型调用或关键词判据。 |
| 隔离副本完整套件109项通过、1项旧诊断断言失败（非法位置在接地前记invalid_location）；修正断言并收尾固定范围/独立入口后，最终定向50项/9子用例通过（61.83秒）。 | 第37–39笔事实哈希、案例、可执行ID、统计、覆盖与停止判断一致；比较排除了已删除failure_patterns和新增空展示列表。skill格式、差异检查通过，已按哈希同步12个文件。新增付费0；不宣称整体语义修复，真实状态仍第39笔6/8且语义失败。 |

- 初次直接批改被自动审批拒绝，未执行；已改用隔离副本验证后获准同步。取消分类未改：现有异常映射不能证明发起者，按设计停止该项，不新增猜测规则。实施及验证记录续写 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的state_convergence。

## v21 — 2026-10-18 状态收敛设计确认与规则固化

- 已确认设计并将五项约束、四组必须区分的状态及单项停止条件并入workflow既有权威文档；替换原有泛化条款，不新建规则文件或检查框架。
- 设计阶段结束，当前进入实施；规则已写入不代表运行代码已完成。第39笔授权已执行失败，无待执行授权复验；新增付费0。实施结果续记原回执state_convergence。

## v21 — 2026-10-18 全skill状态设计静态审计（未实施）

- 沿事实、字段、任务、来源游标、停止与导出追踪状态消费者：主要简化点是可执行动作判定分散、hard_cell混合缺证与调度抑制、任务占用双重记录；字符串差异直接生成CONFLICT存在语义代理风险，不能用自动接受或新增模型调用补救。
- 优先设计由既有调度器统一决定可执行动作和无动作原因，blocked/running等展示由事实派生；诊断日志不另成调度层。停止原因及双审/准入定义保留，导出状态本已派生，不为枚举数量做改造。
- 仅静态审计，未修改运行代码、未运行测试或在线复验，付费0；第39笔仍6/8且语义失败。证据与设计边界续记原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的state_design_audit_20261018；先完成调度状态收敛设计，不恢复语义修补。

## v21 — 2026-10-18 优先简化：移除未应用增量与重复规则

| 删减 | 验证与限制 |
|---|---|
| 移除未应用到历史workspace的reject-review命令、事件判定、导出/展示分支及专用测试；协议删除重复的三类个案校准段落，保存样本与历史回执保留。相对本轮开始删除117行（代码44、测试55、规则18），保留已去重的接受/覆盖判断及原有守卫。 | 第37–39笔事实与派生结果一致；34项/134子用例通过，skill格式及diff检查通过。本次付费0，无新门控或状态；撤回能力现已移除，历史副本实验不代表原件已更正。 |
| 当前工作优先整体简化，具体语义修复暂停。 | 真实状态仍第39笔原生6/8、语义失败、未准入/评分；不宣称简化修复语义。结果见原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的simplification_20261018。 |

## v21 — 2026-10-17 显式撤回接受（仅副本验证；2026-10-18已移除）

| 发现与修复 | 验证与限制 |
|---|---|
| 事后语义失败此前仅记执行回执，原生接受组合不会消费该判断。增加reject-review显式入口，复用online.events绑定原候选/原评审digest并记录理由，统一接受规则排除被撤回记录；不改原评审、不新增运行状态或自动语义检测。 | 第39笔副本撤回inputs_and_outputs及existing_practice后可用字段6→4，其他字段保留；导出显示未接受候选及撤回理由，原reviews/原workspace不变，无重审调用。原件尚未应用，不能把副本结果写成历史已更正。 |
| 错绑定、错digest、空理由、重复撤回及运行中撤回拒绝；恢复投影不会恢复已撤回接受。 | 6项/3子用例通过（33.93秒），本次付费0。已完成批次的旧覆盖见证可能因撤回失效，沿用导出一致性拒绝，不自动重写停止历史。原回执explicit_review_withdrawal保存可审阅请求与副本结果；当前真实状态仍第39笔语义失败、未准入/评分。 |

## v21 — 2026-10-17 通用能力边界与人工视图修正

| 发现与修改 | 验证与限制 |
|---|---|
| supported/FILLED是满足接受契约的评审记录，非代码证明的语义真值；归属与语义是不同职责，非两票独立语义核验。撤回换judge方案，模型配置不改。人工视图此前隐藏summary，现展示原始总结及明确返回的空列表；人工verified改显示“人工归属抽查达标”。 | 第39笔六字段总结逐项核对可见，输入输出/既有方案各四类空列表可见，新增总结HTML转义验证通过；重渲染现有视图，原batch及事实哈希不变。本次付费0、无新增模型调用/门控/状态，不从总结自动补发现。 |
| 协议同步区分模型判断、确定性接地、自检和真人归属抽样，保留双审职责与原接受门槛。 | 真实状态仍第39笔6/8、语义失败、未准入/评分；本次解决审阅可见性和过度表述，不宣称语义修复。细节见原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的capability_boundary_revision。 |

## v21 — 2026-10-17 全skill防同构膨胀设计审计与简化（离线完成）

| 修改 | 范围与验证 |
|---|---|
| 审计长度/完整句/schema代替语义保证、重复自评冒充独立核验、失败后叠加门控三类同构风险；单一发现表示不再列为优先修复。将不变量、默认策略、诊断及六类职责集中到workflow既有权威节；配置不等于可放宽，候选拒绝与整笔停止分别归属。替换此前重复职责段落和过期单笔准备说明，不新增规则引擎、状态、配置或文档层。 | 核对现有语义拒绝本已不自动停止整批；不凭假设重写。Track、双审、评分和来源/预算边界不变；当前暂停具体语义修复及付费。 |
| review_policy统一投影/导出/统计三处接受组合；coverage_policy让覆盖见证与缺口诊断消费同一字段/评分规则，删除重复判断。 | 第37–39笔投影/案例/统计/调度/停止及事实哈希前后相同；34项/134子用例集成与锚点检查通过（115.54秒），稀疏证据保持缺证且无覆盖见证；本次付费0，不改变第39笔6/8、语义失败、未准入/评分。结果写入原回执 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json` 的skill_design_optimization。 |

- 端到端设计复核收尾：第39笔未执行搜索/准入/评分，相关边界仅核对代码及此前离线集成结果；确认语义零纠错，其他契约一次格式纠错仍计预算。合并防膨胀重复要求7→4条，修正workflow残留“短引”措辞；本次仅文档、付费0，执行基线与原生事实不变，不重跑测试。记录见同一回执skill_design_optimization.end_to_end_review；设计审计收束，不继续滚动扩审。

- 设计收束后核对现有模型配置：仅main/qwen3.8-flash有配置凭据，judge同时承担归属和语义（第39笔15/16请求），不能声称仅替换语义。已在原回执next_scheme_proposal准备“只替换现有judge、原生链路直接验证”的待选方案；不增加评审步骤或付费诊断，不声称换模型有效。待用户指定替代模型/配置再固定预算；本次付费0、代码/提示词/共享配置未改，真实状态仍第39笔失败。

## v21 — 2026-10-17 第三十九笔校准后唯一真实复验：方案停止

| 实际执行与结果 | 证据及边界 |
|---|---|
| 第三十九笔 DIQKD（基线 `7e21c545`）：16/64次调用、123.58/1200秒，已知143028 tokens（15/16响应有用量，末次中断用量未知；USD未知），原生6/8 FILLED，语义验收失败，未进入准入/评分。inputs_and_outputs总结承认密钥轮固定Xi=0、Yi=2，但发现列表全空；existing_practice也遗漏已承认的设备/来源表征假设。agent按止损边界SIGINT停止，原生 incomplete / user_aborted / CancelledError；非用户撤销授权，无自动续跑。 | 全新workspace：`artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/workspace`；命令为原生open-source，固定arXiv:2109.14600v2、相同config，归属和语义重新执行，未继承旧判定。 |
| 六份已完成语义响应的发送schema、原文锚点与请求哈希回放通过，固定基线及配置不变；这不改变语义失败。real_world_problem归属被拒，deployment_boundary语义响应中断；数值强弱矛盾判据未被本笔候选直接触发，不宣称有效。success_criteria所选Q123片段缺CHSH阈值命题、理由依赖前文，保留证据承载疑点。原生判定不改写，人工视图不是语义验收通过证明。 | 1次抽取、8次归属、7次语义请求（6次响应）；6份结构/锚点回放通过不等于语义通过。只读核对事实状态哈希不变；检查为agent核对，不冒充真人复核。本笔没有代码或提示词修复、纠错调用。 |
| 一轮离线校准及唯一授权复验均已完成；当前判据方案停止，不追加提示词、结构补丁、样本或付费试错。下一步仅为另行决定后续方向；不自动实施三层框架，不据一次失败否定整类自然语言方法。 | 命令、预算、原始调用定位、逐字段观察和成本见 `artifacts/quantum-scout/validation/v21-calibrated-semantic-validation-20261017/execution.json`；不将旧离线付费0误写为本笔零费用。 |

## v21 — 2026-10-17 三类判据单轮离线校准（第三十八笔后）

| 发现与修改 | 验证、成本与边界 |
|---|---|
| 分开处理第37笔证据承载、第38笔限定遗漏及矛盾误分类；证据协议明确逐限定对照、发现不按候选失效筛选、命题范围/量词/指标对齐。在线只替换矛盾比较指令，schema/调用数不变，无关键词判定。 | 10个保存样本的agent标注含6个失败、4个局部正例；10/10原始请求哈希、响应、候选和证据绑定核验通过，14项/28子用例回归通过（22.09秒），两笔事实状态哈希不变。系统指令4591→4758字符，schema及请求payload不变（非token/费用估计）。正例仅针对指定命题；没有已修正部署字段或同字段数值蕴含正例，不代表独立复核或模型稳定性。 |
| 本轮离线校准后至多一笔另行授权复验；无法有据区分、需追加例外/表面规则，或复验任意语义失败，停止当前方案，不追加提示词、不自动重跑；后续方向另行决策。离线仅作必要筛选，不预测线上稳定性。 | 本次新增付费调用0，对应第37/38笔保存响应校准范围；真实状态仍第38笔7/8、语义失败、未准入/评分。样本 `examples/semantic-calibration.json` 供审阅；可复现命令及结果续记原回执 `artifacts/quantum-scout/validation/v21-full-evidence-validation-20261017/execution.json` 的offline_semantic_calibration。 |

## v21 — 2026-10-17 第三十八笔后发现分类修复（离线）

- 保存响应显示deployment_boundary用“是否使候选无效”筛掉已承认限定，success_criteria把自述兼容的结果归入矛盾；这是观察，不证明模型能力边界或提示词因果。将同一次评审改为先盘点相关限定、再判候选，四类定义进入输出schema；矛盾须说明同范围下互不相容的候选/原文命题，支持不足由结论处理。保留已有字段、完整证据和守卫，无新增模型调用或关键词纠错。
- 14项/28子用例回归通过（22.53秒）；8份历史响应按新schema与原文绑定回放仍通过，包括两份语义失败，明确不能据此宣称语义修复。schema紧凑JSON4572→5420字符（非token/费用），原输入和事实状态不变；本次付费0，真实状态仍第38笔7/8、语义失败、未准入/评分。
- 修改、逐字段回放与下笔验收范围写入同一 `artifacts/quantum-scout/validation/v21-full-evidence-validation-20261017/execution.json` 的offline_semantic_classification；下一步是新授权单案例复验，核对限定保留、矛盾分类及所有已完成字段，而非再加结构守卫。

## v21 — 2026-10-17 第三十八笔完整证据真实验证

- 第三十八笔 DIQKD（基线 `325bb3aa`）：20/64次调用、188.71/1200秒，已知233454 tokens（19/20响应有用量，末次中断用量未知；USD未知），原生7/8 FILLED，inputs_and_outputs被语义拒绝；未进入准入/评分。完整证据迁移已真实触发，但整体语义验收失败：deployment_boundary总结承认非类空间分离却未列发现，success_criteria将理由自述无直接矛盾的证据放入矛盾列表。agent确认后SIGINT停止，原生 incomplete / user_aborted / CancelledError；非用户撤销授权，无自动续跑。
- 抽取/归属/语义/导出真实使用同一完整证据，7项主证据142–322字符，逐项原文、grounding.matched_text和哈希偏移一致；八个完成语义响应符合发送schema，请求哈希/基线/配置通过。constraints完整假设句修复了第37笔目录表达缺口；输入泛称随机的候选由固定密钥轮原文拒绝，缺证不补齐。这些局部观察不证明整体语义通过，不作两笔因果推论。
- 人工视图已生成，显示完整原文、位置、来源、理由和条件证据；运行后补显示既有semantic_mismatch未接受候选，2项定向离线回归通过（3.73秒），从原batch重渲染、事实状态哈希不变，无模型调用。规则/实现迁移不维护独立短引；本笔后执行代码仅人工渲染变更，无链路续跑。回执 `artifacts/quantum-scout/validation/v21-full-evidence-validation-20261017/execution.json` 保存观察和成本；下一步用保存响应处理条件遗漏及矛盾分类，不增加短引长度补丁或付费诊断。


## v21 — 2026-10-17 完整原文证据迁移（第三十八笔准备）

- 用户明确授权替换过时50字符规则；抽取与语义评审改用完整句ID，沿用quote字段作为唯一所选证据，不存展示短引。ContextGem原句仅附ID，按允许的空白归一定位回原文；来源哈希/偏移、接地、独立双审、未知/重复ID与null停止均保留，同句多条件在同组一次引用并完整说明。人工报告和所有案例草稿直接展示同一证据、来源、位置、版本、偏移及评审理由，长文仅界面折叠，原文HTML转义。
- 离线跨层回归首轮65通过/3失败/136子用例，三处为旧归一文本、旧提示及51字符拒绝断言；按新契约改为原文保留/空证据拒绝后，抽取与在线夹具63项/12子用例通过（78.29秒），最终原生人工视图端到端1项通过（1.99秒）。第37笔四页保存输入目录416→164项，失败40字符短语由完整假设句覆盖；未重绑历史ID或改写判定。输入量化与局限见新回执offline_validation，不把字符变化当token或费用变化。
- 本次修改付费0，真实历史仍第37笔6/8、语义失败；第38笔仅准备、尚未执行，授权上限64调用/1200秒、新workspace，不自动续跑。回执 `artifacts/quantum-scout/validation/v21-full-evidence-validation-20261017/execution.json`；迁移语义效果须由本笔实际结果验证。


## v21 — 2026-10-17 短引设计复核（第三十七笔后）

- 用户质疑反复短引修补后，核对最早可查提交bb79c34的evidence协议及现行/归档规则：50字符作为项目引用约束已存在，未在所查材料找到50能保留完整语义的推导；更早设计意图未知。现行短引同时承担定位展示与独立承载发现全部限定，存在职责耦合；可追溯性本身依赖原文/哈希/位置/偏移，不要求50字符证明完整主张。
- 同一第37笔constraints四页请求离线比较：现有416项/目录示例JSON23447字符，逐词起点50字符重叠窗3090项/179236字符；后者覆盖失败40字符短语但输入明显膨胀。沿现有近似分句规则为164项/21111字符，最长629字符，仍需处理缩写/长句；这些仅是目录量化，不是完整请求token、费用或语义效果。付费0、执行代码未改，真实状态仍第37笔6/8、语义失败、agent中止。
- 不提交重叠目录补丁。建议明确绑定完整原文证据跨度，短引仅展示定位，接地/哈希/独立双审/缺证门保持；该职责变更需用户明确覆盖AGENTS既有50字符证据边界后实施。方案、量化与局限追加同一 `artifacts/quantum-scout/validation/v21-regex-compatibility-validation-20261017/execution.json` 的short_quote_design_review，不另建报告或事实账本。


## v21 — 2026-10-17 第三十七笔正则兼容真实复验

- 第三十七笔 DIQKD（基线 `113c9d11`）：14/64次调用、119.53/1200秒，已知162126 tokens（13/14响应有用量，末次中断用量未知；USD未知），原生6/8 FILLED；语义验收失败。六个已完成语义响应已给出完整理由，constraints也列出条件，但所选短引仍缺理由声称的否定、私有随机性或可信计算机限定。agent确认失败后SIGINT停止，原生 incomplete / user_aborted / CancelledError；非用户撤销授权，未准入/评分，不续跑。
- 六个保存语义响应通过发送schema；请求哈希、固定基线及配置通过。相较第36笔，本笔观察到完整理由、constraints条件列表非空，但不能从两笔变化推断正则修复因果，更不能认定整体保真通过。parties Q69缺否定，constraints Q74缺privately、Q70不足以支持四项假设；原生事实不改写。
- 保存原文有40字符连续短语 `privately choose random\nclassical inputs`，符合50字符上限却跨目录Q73/Q74，没有完整可选项；这是可复现的目录表达缺口，不等同模型能力或任务过载。无合适片段仍应null停止，不能用上下文补足所选短引。下一步离线修复/回放目录切分边界并量化输入增量，不追加付费诊断。 本轮未修改执行代码，无纠错或自动续跑；agent原文比较不冒充真人审计。字段/call_id/短引/理由、成本与原生停止写入同一回执 `artifacts/quantum-scout/validation/v21-regex-compatibility-validation-20261017/execution.json`。


## v21 — 2026-10-17 第三十六笔后正则兼容修复

- 保存原响应已含单字符理由，客户端先保存全文再解析，未发现首字符截取。原schema非空白 `\S` 在搜索匹配下接收完整句子、整串匹配下仅接收单字符；改为共享的等价整串非空白表达，允许多行理由，不加长度门槛、不放宽空白/证据守卫。网关实际解码语义仍未证实，不将相关性当根因。
- 13项/28子用例离线回归通过（20.68秒），覆盖真实SDK MockTransport、完整/多行/中文理由和空白拒绝；六份保存请求仅四处pattern变化，schema8524→8604字符，输入不变、调用增量0。五份历史响应仍结构/绑定通过但语义失败，原生事实不改写；这不是语义修复通过。
- 本次付费0，对应在线历史为第三十六笔13次、5/8、agent中止，修改后未在线复验；归因、回放、成本与下一笔验收标准追加 `artifacts/quantum-scout/validation/v21-semantic-acceptance-validation-20261017/execution.json` 的offline_regex_compatibility。下一步仅在新笔授权后验证完整理由及条件/限定保留，不追加独立诊断调用。


## v21 — 2026-10-17 第三十六笔真实复验

- 第三十六笔 DIQKD（基线 `2c776f45`）：13/64次调用、109.79/1200秒，已知143133 tokens（12/13响应有用量，末次中断用量未知；USD未知），原生5/8 FILLED；语义验收失败。五个已完成语义响应的理由/总结均为单字符，constraints候选及原文含隔离、私有随机输入、可信经典处理，但发现列表为空。agent发现后发送SIGINT停止，原生为 incomplete / user_aborted / CancelledError；非用户撤销授权，未进入准入/评分，不续跑。
- 请求哈希/执行基线通过；已知用量不是完整成本。第35笔条件遗漏在第36笔constraints仍可观察；新出现的单字符理由与schema `\S` 的整串匹配解释相容，离线search/fullmatch对照确认解释差异，但服务端实现及因果未证实，不认定模型能力或任务过载。无执行代码修改，无纠错、退路或续跑；agent核对不冒充真人审计。原生事实不改写。
- 同一回执 `artifacts/quantum-scout/validation/v21-semantic-acceptance-validation-20261017/execution.json` 保存各字段call_id、原生停止、成本及语义验收结果。下一步仅离线核对正则传输/匹配语义，暂不加结构补丁。下方35笔表保留历史范围，本笔为新增第36笔。


## v21 — 2026-10-17 归因闭环与方案校准

本轮仅核对三次提交、v21变更记录、执行回执及现行评分/交接契约；新增模型调用0，无新workspace。下表是历史记录的决策索引，不是新事实源；FILLED不是语义通过率，根因栏描述可观察失效，不将模型能力边界当作已证实原因。历史原件与下文逐笔详情保留。

| 笔次 | 调用 / 八字段FILLED | 失败组件或语义发现 | 对应修复 → 后续在线结果 |
|---|---|---|---|
| 1 | 13 / 未在摘要注明 | 55字符纠错失败 | 定点纠错 → 2触发，仍有后续契约错误 |
| 2 | 36 / 8 | C2超长、C3缺证空引文 | 准入候选契约 → 3未到Track，不算目标复验 |
| 3 | 18 / 5 | 纠错根数组缺外壳 | 无损外壳处理 → 4未触发该分支 |
| 4 | 26 / 8 | C4理由混用C3；QS回退契约 | 字段规则绑定 → 5未到Track |
| 5 | 13 / 4 | success_criteria非原文短引 | 非原文纳入定点纠错 → 6仍原样回传 |
| 6 | 7 / 1 | constraints非原文纠错失败 | 改原文词范围选择 → 7结构通过但威胁含义偏移 |
| 7 | 21 / 7 | 短引语义漂移；固定来源缺口误报预算 | 独立保真及范围耗尽分类 → 8先遇长度错误；12耗尽分类触发 |
| 8 | 16 / 5 | quantum_mechanism_role纠错后仍57字符 | 统一范围选择 → 9仍超长 |
| 9 | 6 / 1 | 所选范围超长 | 加合法终点 → 10仍有越界61字符 |
| 10 | 16 / 6 | 范围终点不遵循 | 预生成短片段ID → 11正文失败、12未触发、13触发 |
| 11 | 0 / 0 | 正文ConnectError，错误停止分类 | source_unavailable及后续获准一次重试 → 22重试触发成功 |
| 12 | 17 / 7 | 量子机制外推非对称安全仍supported | 主张/威胁提示 → 尚无同一目标语义通过证据 |
| 13 | 15 / 5 | 保真输出说明加JSON | JSON模式 → 14契约接收，绑定语义仍错 |
| 14 | 25 / 7 | 选this却解释原引；重复句映射 | selected_quote绑定 → 15绑定触发，supported/理由仍不一致 |
| 15 | 24 / 6 | 抽取超长、章节代替归属、保真判断矛盾 | 锚点及归属提示 → 16触发但超时，不证明语义修复 |
| 16 | 12 / 5 | 错句；success_criteria归属超时 | 局部输入去重 → 17运行，仍抽取缺口；无成功率因果证据 |
| 17 | 25 / 6 | 超长及引用错句 | strict抽取schema → 18/19发送后仍超长 |
| 18 | 13 / 3 | 三条超长，主动中止 | 核对HTTP传输 → 19确认服务返回仍违规 |
| 19 | 1 / 0 | strict maxLength未约束52字符 | 原生数组+本地逐项隔离 → 20隔离触发，仍缺现实问题 |
| 20 | 21 / 7 | real_world_problem超长/错句 | 抽取片段ID → 21真实触发；不保证语义正确 |
| 21 | 37 / 8 | QS拒绝分支完成；C2错句 | QS优先调度 → 22触发，S4语义拒绝不可靠 |
| 22 | 32 / 8 | S4把实验室状态等同不可实现 | S4规则澄清 → 23仅抽取触发；26语义触发但理由无原文支持 |
| 23 | 31 / 8 | S3选detection efficiency丢数值 | 数值/单位保留提示 → 24触发，换成数量却仍不表达威胁边界 |
| 24 | 15 / 4 | inputs_and_outputs数量短引不支持发现 | 补选择器原判断/上下文 → 25确认送达仍失败 |
| 25 | 23 / 6 | success_criteria选it；另有丢no仍supported | 代词/否定守卫 → 26触发，数值单位仍丢失 |
| 26 | 52 / 8 | 评分3/6；implementation_feasibility选≈ 2丢单位；S4理由虚称原文明示 | 百分数完整性 → 27未到该评分目标，不能声称已复验通过 |
| 27 | 23 / 7 | deployment_boundary选loophole.不表达发现 | 包含片段去重 → 28触发，保真回传改写/超长 |
| 28 | 11 / 3 | quantum_mechanism_role保真改写所选43/50字符为65/59字符 | 保真改ID → 29绑定通过但S4语义拒绝；30又出现自造ID |
| 29 | 32 / 8 | S4保真not_supported；实现理由不获原文支持 | 按finding类别澄清S4评审 → 30未到S4，目标未验证 |
| 30 | 21 / 7 | deployment_boundary保真第三ID自造 | 单次AnchoredJudgments替代纠错/保真 → 31触发但结构失败 |
| 31 | 3 / 0 | 首评审冒号键/缺字段/reason | 输入去重 → 32仍结构畸形，不能证明输入长度是根因 |
| 32 | 11 / 4 | inputs_and_outputs字段嵌进转义字符串 | 严格语义schema → 33未调度、34结构接收但一致性拒绝 |
| 33 | 1 / 0 | ContextGem未知P0-S55令整批失败 | 引用逐项隔离 → 保存响应离线拒1留7；34无坏项，拒绝路径未在线触发 |
| 34 | 3 / 0 | real_world_problem发现标记true但列表空 | 删除冗余标记 → 35列表结构接收；条件遗漏仍存在 |
| 35 | 9 / 3 | quantum_mechanism_role非法位置；已接收constraints漏条件、parties锚点缺限定 | 5567924目录约束+发现先行 → 离线拒历史结构错误；修改后尚无新笔在线复验 |

关键回执均在项目 `artifacts/quantum-scout/validation/`：23=`v21-s4-rule-validation-20261016`，25=`v21-counter-context-validation-20261016`，26=`v21-counter-lexical-validation-20261016`，27=`v21-counter-percentage-validation-20261016`，29=`v21-framework-reuse-validation-20261017`，30=`v21-s4-semantics-validation-20261017`，31=`v21-anchor-review-validation-20261017`，32=`v21-cost-validation-20261017`，33=`v21-strict-output-validation-20261017`，34=`v21-reference-isolation-validation-20261017`，35=`v21-list-contract-validation-20261017`；各目录读取同一 `execution.json`，原始调用ID与workspace沿其引用。23顶层live_model_calls=0为准备期残留，实际result.model_calls=31；不可机械取顶层0当未在线执行。

**任务拆分评估：** 已证实语义不支持、数值单位丢失、限定遗漏跨架构发生；未证实单次评审过载。旧分步链路第25笔已有否定丢失被supported，新单次链路第35笔也有遗漏，因此不能以再次拆分本身作为修复依据。优先用第35笔保存请求核对所需限定是否可由目录表达、选择是否匹配理由、列表是否保留已识别条件；已有offline_convergence给出相邻锚点包含限定的证据。缩小文档范围可能漏掉跨页条件，不应未经覆盖核对直接启用；新增分步请求也不满足“不叠加调用”的既定约束。当前维持既有调用数，下一笔只检验已收敛契约与明确语义标准，失败再按实际层次决策，不追加结构补丁。

**方案校准：** 三次提交统计已在skill仓库核实；提交聚合多个运行前后改动，不能把“提交之后”当作所有改动均进入某次运行，须用回执执行基线。评分最低有效维数及不足时归一分null已有配置与实现，NLC五维、QS六维，不能统一写4/6；当前最低有效维数为NLC四维、QS五维；默认三维会永远达不到该门槛。完整度标签可评估，但不先改变默认调度。sandbase已有直接加载、真实宿主账本及validator验证（`sandbase-direct-20261017/execution.json`），原生交接仍未验证；不将置信度自动映射为原生证据、不以npm失败触发规则模块降级。先沿现有阶段门完成单案例语义/准入/评分，再扩展集成。

本轮为提交级离线事实核对，不是新模型复验或真人审计；系统级最新仍第35笔incomplete/error/contract_violation、3/8，未准入/评分。执行代码、历史判定和运行状态均未改；不新增就绪度状态或平行台账。下一步唯一动作：按第35笔 `offline_convergence.next_live_validation` 的通过/失败标准，在逐笔新授权后执行同案例新workspace（上限64调用/1200秒），以语义条件和限定保留验收，不能只看结构/FILLED。


## v21 — 2026-10-17

- 明确项目AGENTS.md文档规则：离线修复/回放/检查也须在CHANGELOG向未参与对话的读者说明发现、修改、实际结果/成本、未验证边界、真实状态及原回执路径；关键限制不能仅留在对话。仅文档变更，付费0。

- 同组件离线收敛：回放第三十四/三十五笔5个保存语义响应，历史结构错误仍拒绝；请求统一约束候选0、位置/锚点ID目录、非空理由，四组共用ID枚举，保留null及哈希/重复/接地守卫，提交前拒绝遗漏候选位置。模型先列发现再给结论，明确支持候选的条件也须列出、短引本身保留所述限定。
- 原文核查发现已通过记录仍有语义缺口：constraints总结有条件但列表空，parties_and_roles锚点缺少理由所述限定；历史事实不改写，不称修复已语义通过。32项/110子用例回归通过，补充位置约束后13项/4子用例通过；原始输入不变，schema2946→8524字符（416 ID仅列一次）、指令3453→3739字符，新增调用0。核查定位、成本与下一笔可观察标准写入第三十五笔同一execution.json；当前原生状态仍3/8，未新笔运行。

- 将同组件契约离线收敛、结构与语义分离、付费复验可观察标准写入workflow职责规则；当前优先级改为先收敛再复验，禁止逐个补丁驱动付费试错。仅规则更新，真实状态仍第三十五笔3/8，付费调用0。

- 第三十五笔：基线2f7d2dab，9/64次、83.33/1200秒、118719 tokens（USD未知）；原生3/8 FILLED，三个新列表契约语义评审通过，第四个 quantum_mechanism_role 的搜索位置为 `],page:1`，本地守卫拒绝，incomplete/error/contract_violation；未准入/评分，基线/请求哈希通过，无纠错或续跑。回执v21-list-contract-validation-20261017/execution.json。
- 运行后将严格schema搜索位置限制为本请求位置枚举，保留本地守卫，历史响应不纠错；原响应符合旧schema、被新schema与原本地守卫拒绝，schema 2946→2991字符，新增调用0，12项相关回归通过（20.36秒）。修复尚未在线复验；已有非空列表通过不能证明整体反证保留及语义保真。

- 收敛第三十四笔标记/列表冗余：AnchoredCounterSearch 仅接收显式发现列表，锚点还原后生成内部 *_found；null/未知/重复 ID 与旧含标记响应仍拒绝，不改写历史发现、不追加调用。语义提示3463→3453字符/字节，证据输入不变，减少3个生成布尔字段；不推算费用降幅。
- 离线检查：第三十四笔保存响应原样回放拒绝；锚点、在线夹具与工作流回归初跑59通过、2失败（114子用例），内部契约夹具及原有超时重试过时断言修正后定向2通过（5子用例）。无新增付费调用，未新建真实workspace；当前仍第三十四笔0/8、incomplete/error/contract_violation，修改后的在线效果待新笔授权。

- 第三十四笔：3/64次、43.31/1200秒、53293 tokens（USD未知），0/8 FILLED；严格json_schema请求实际返回且结构校验通过，但首字段两类发现标记true、证据列表空，一致性守卫拒绝，incomplete/error/contract_violation。引用目录保存成功、无非法引用项，逐项拒绝本笔未触发；请求哈希/基线通过，无纠错/退路/续跑。回执v21-reference-isolation-validation-20261017/execution.json。

- 第三十三笔后补齐ContextGem批量引用映射前的逐项隔离：按本轮保存段落/句ID目录拒绝整项非法候选，目录不重复发送模型，原响应及坏引用保留，不猜配/删引用/重试。历史响应离线回放拒绝parties_and_roles一项、其余7项仅通过过滤；34项/4子用例集成回归通过（40.85秒），含真实库混合好坏引用及全坏停止，付费0。真实状态仍0/8、严格schema未验证，结果追加原execution.json。

- 第三十三笔严格输出复验：1/64次、30.50/1200秒、32152 tokens（USD未知），问题定义0/8；ContextGem返回不存在的P0-S55（保存请求P0有50句），引用映射拒绝整批，incomplete/error/LLMExtractionError。未调度严格schema语义请求，不能判断网关支持；无退路/纠错/续跑，执行基线及请求哈希通过。下一步保存响应复现引用逐项隔离；回执v21-strict-output-validation-20261017/execution.json。

- 第三十二笔后修复输出协议：新增显式semantic_output_format=json_schema，由既有LangChain生成严格schema并经response_format发送，提示词不重复；原JSON模式保留兼容配置，无自动降级。保存5次响应回放接受4次完整响应、拒绝1次畸形响应；11项锚点回归与1项网关400不重试回归通过。新schema3151字符、旧2656字符，增加495字符用于结构约束，非节费实证；付费0，严格模式网关尚未在线验证，追加原execution.json并准备新config。

- 第三十二笔节约优化真实复验：11/64次、105.71/1200秒、143348 tokens（USD未知），问题定义4/8 FILLED，未准入/评分；第5候选inputs_and_outputs的语义响应将后续字段写进segments_searched转义字符串，缺字段，incomplete/error/contract_violation停止。4次锚点还原与双审通过、请求哈希全通过，未追加纠错/保真/退路；首次语义输入28317→18052 tokens仅为跨笔观测，不证明因果或费用比例。搜索/引用暂停未触发，不续跑；回执v21-cost-validation-20261017/execution.json。

- 全 skill 节约审计：入口引用统一规则；紧凑模型JSON/schema、仅传目标字段规则、ContextGem规则去重、查询失败按目标筛选；已发抽取请求失败不再转原生退路，引用传输不自动重试，搜索/引用429或超时暂停服务。清除旧语义纠错文案。全量99项/116子用例通过；后增集成检查33项/4子用例通过，1项初始化夹具修正后定向通过（1.04秒）。保存请求回放ContextGem系统12258→10988字符、归属JSON12842→12810字符，非token/USD降幅；付费0，真实状态未变。回执v21-skill-cost-audit-20261017/execution.json。

- 按用户要求将节费目标写入workflow职责规则并由AGENTS引用：所有修改尽量减少模型调用和输入，不牺牲证据及独立双审。语义请求去掉重复上下文、锚点按位置分组、紧凑JSON；第三十一笔保存请求用户消息84705→50084字符（−40.87%），416锚点及上下文/其他账本字段无损，输出schema不变。11项定向离线回归通过（19.02秒），新增付费0；字符减少不等于同比费用减少，结构异常原因及真实效果仍未验证，结果追加原execution.json。

- 第三十一笔3/64次、44.43/1200秒、65319 tokens（USD未知）：新workspace问题定义0/8 FILLED，首字段uncertain，未准入/评分；incomplete/error/contract_violation。首次AnchoredJudgments响应含无效冒号键、缺必填字段及reason，锚点还原前拒绝；未追加纠错/保真，S4未验证，不续跑。请求哈希通过，上下文重复可精简但不能据n=1归因；回执v21-anchor-review-validation-20261017/execution.json。

- 用一次 AnchoredJudgments 原始语义评审替换反证短引纠错与独立保真：只返回已保存原文片段ID和发现理由，程序校验请求哈希、还原短引/位置并执行既有守卫；null/未知ID不纠错、不静默删发现。旧纠错测试单文件原样保留于archive/tests，活跃回归首轮97项/116子用例通过、1项旧范围停止断言失败，按新契约修正后定向1项/5子用例通过；保存第三十笔输入产生416个≤50字符锚点、旧自由引文响应被拒绝，doctor ready，付费0。准备回执v21-anchor-review-validation-20261017/execution.json；原生第三十笔7/8未变，新架构未真实验证。

- 第三十笔21/64次、159.88/1200秒、182294 tokens（USD未知）：新workspace八字段7/8 FILLED，部署边界uncertain，未进入准入/评分；incomplete/error/contract_violation。保真第三个quote_id被改为自造短语，前两ID正确仍拒绝整项；未到S4，不能验证其语义修复，不续跑。回执v21-s4-semantics-validation-20261017/execution.json；下一步保存响应回放修ID绑定。

- S4评审修复：保真按 finding 类别核查，威胁边界不必反驳候选，仍保留“最关键”等原发现强度；主评审逐项核对实现条件，不将硬件描述冒充明确无需容错。修改后定向31项及7个子用例通过（42.18秒），离线doctor ready；付费0，真实效果未验证。新笔准备回执 v21-s4-semantics-validation-20261017/execution.json，待逐笔授权，原第二十九笔状态不变。

- 撤回 sandbase 双搜索能力硬门槛；workflow 固定宿主账本到既有正文入口的交接边界，不新增导入器。保存响应中两条短引定位通过，篡改短引及缺少双审均拒绝；偏移仅针对宿主响应，非原生接地。付费调用0，第二十九笔S4状态不变；更新同一 sandbase-direct-20261017/execution.json。

- sandbase 临时加载：npm 网络失败后直接读取上游 Skill/schema，使用原生 validator 验证真实两来源账本；未知来源及虚高置信度拒绝，现有 Candidate 拒绝直接账本和 high。1/6搜索、3/6正文打开（2成功）、付费模型0；单一搜索渠道仅为覆盖局限（已撤回其硬门槛）；原生接入未验证，未写入事实或启用规则降级。回执 sandbase-direct-20261017/execution.json。

- 第二十九笔32/64次、280.83/1200秒、618989 tokens：原生8/8，QS S1–S3=true、S4未完成，未评分；incomplete/error/contract_violation。两次保真ID及保存请求哈希均通过，先supported后S4 not_supported停止；3次ContextGem目录保存路径触发，原生退路未触发。S4硬件推断不等于原文明示无需容错，所审页5–6无对应措辞；保留原判断与回执，不自动续跑。回执v21-framework-reuse-validation-20261017/execution.json。

- 完成七框架参考与现有组件逐项核对：修复ContextGem目录仅内存解析及原生退路自由生成短引，统一保存请求ID解析；共享片段切分器，保留候选隔离、接地和双审。普通日志改为锁内原子写事实，失败事件仍投影。状态/恢复、算分/停止沿用已有实现，不引入第二套数据库、缓存或规则；分组离线共118项回归/123个子用例通过：主组80通过、1项新增测试缺少在线初始化，修正后与ContextGem内存丢失检查定向2项通过；其余在线/固定正文37项通过。无网络doctor ready，付费调用0；下一笔仅准备，真实效果未验证。

## v21 — 2026-10-16

- 保真复核复用ContextGem的ID引用方式及scientific-agent-skills的证据ID/判断契约：选择从保存请求取回选项，复核仅输出quote_id/support/reason，校验请求哈希及ID完整性；保留50字符、一次纠错与语义拒绝，不新增账本/缓存。无网络回归50项及108个子用例通过（139.91秒；首轮一条旧selected_quote断言已改为ID查回）；原第二十八笔状态不变，付费调用0，真实效果待全新workspace复验。

- 文档补齐七个框架的具体参考能力与接入边界，集中于workflow，SKILL仅增加路由；明确抽取ID已实现、保真ID尚未实现，区分结构校验与语义证明，不把占位审计写成可复用实现。本次仅修改文档，无付费调用。

- 按用户要求确立代码/模型/持久化职责：确定性规则归代码，不可变证据落盘后按ID引用，模型仅作语义判断；workflow为规则权威，AGENTS引用。保真ID契约已实现并通过下述离线验证；其余确定性链路优化按组件推进，尚未真实验证。

- 第二十八笔11/64次、95.18/1200秒、108508 tokens：原生3/8，quantum_mechanism_role保真响应把43字符选中短引换回65字符原长引，另一50字符选项回传59字符改写，触发incomplete/error/contract_violation；未到准入/评分。包含去重真实触发，候选3/3/1且选择均≤50，不能据此认定语义修复有效。保存响应离线回放仍拒绝；回执v21-counter-contained-validation-20261016/execution.json，无运行后代码改动、不续跑。

- 第二十七笔后短引修复：仅对已接地超长引文按原文位置去除被更长合格片段包含的候选，不加词法黑名单，不改非原文搜索范围、50字符、一次纠错及保真守卫。保存请求三组候选12/75/8→3/8/1，排除loophole.并保留含closing the detection loophole的原文上下文；28项回归及7个子用例通过（初跑3项旧选项夹具失败，改用保留片段后通过）。保真unclear仍停止；未付费复验。

- 代码去重：三处案例证据遍历归coverage_policy.case_evidence，保留顺序及调用方筛选；checkpoint增量键由validate_batch统一定义，生成器复用；删除add-case重复schema写入。不新增缓存/开关/模块；19项集成回归及101个子用例通过，第二十六/二十七笔只读回放输出一致。未付费复验，后续须新workspace。

- 派生视图简化：导出通过build/render校验后仅持久化checkpoint计数，移除尾部SOCM重建和schema重写；prepare移除persist前重复schema写入。调度投影、原子事实写入、锁及显式repair保留；19项集成回归及101个子用例通过，第二十七笔只读回放导出一致。执行基线已变，真实效果未付费复验，下一笔须新workspace。

- 第三轮文档整理：问题定义缺证规则归一，短引纠错按范围/选项/选择/保真四步表达，预算与服务失败归为一张处理表；移除重复来源规则及固定Frontier案例数推算。八字段表、执行代码、配置不变；生成schema、执行基线、链接/锚点及diff空白检查通过，本轮付费调用0。

- 第二轮文档去重：合并批次checkpoint、查询计数、派生状态和审计重复说明；failure_class枚举归批次契约，README改引用维护入口。依据现有实现修正未评估tracks缺证占位及counter_evidence_invalid枚举；生成schema与执行基线前后完全一致，链接/锚点及diff空白检查通过；本轮付费调用0。

- 第二十七笔23/64次、153.75/1200秒、298735 tokens：原生7/8，deployment_boundary纠错选loophole.，保真unclear触发incomplete/error/contract_violation；未到准入/评分，百分数目标失败场景未复验。回执为v21-counter-percentage-validation-20261016/execution.json，不续跑。
- 文档去重：SKILL改路由，维护说明归workflow，准入/评分语义及短引纠错归evidence；保留八字段表、配置与执行代码，不新增规则文件或候选筛选。删除固定调用下界，修正批次文档error状态写法；生成schema与执行基线前后完全一致，文档相对链接检查通过；不代表真实链路通过。

- 第二十六笔后免费修复：纠错候选排除不含字母的孤立数字/符号，正文百分数的比较符、数字和单位（%、％、‰）不可切开；不是通用单位解析或语义替代。保存请求回放排除≈ 2、保留34字符数值上下文候选；26项测试及7个子用例通过。S4实际复核页5–8含经典硬件实现但无明确无需容错措辞，理由措辞未获原文支持，原生true不改；修复真实效果待新笔授权。
- 第二十六笔52/64次、414.28/1200秒、1051491 tokens：原生8/8，QS true/true/true/true，S4新说明已进入语义复核，评分真实执行13次调用、填3/6维（3/5/5），部分和13、归一分null。implementation_feasibility纠错选≈ 2，丢百分号及效率含义，保真not_supported而error/contract_violation；未完成评分/纳入。S4理由声称正文明确说无需容错，提取正文未找到对应明确措辞，保留原生true而不宣称语义已验证；不自动续跑。
- 第二十五笔后免费修复：反证纠错候选筛除纯英文代词/功能词及无词字符片段；已接地超长引文缩短须保留显式英文否定标记及次数。保存请求回放排除it及丢no的历史选择，保留接地/绑定/保真及一次纠错；25项测试和2个子用例通过。作用域、隐式否定和其他语言仍靠语义复核，不能宣称语义正确；随后第二十六笔真实触发并进入评分，但数值/单位短引仍失败。
- 第二十五笔23/64次、177.36/1200秒、485799 tokens，原生6/8；4次选择/保真请求已确认原始判断及正文上下文一致，success_criteria仍从7134个选项选成it，保真unclear触发error/contract_violation，未到Track/评分。另有省略no further的短引获supported，不能认定语义正确；保存原生事实，本轮未新增代码修复，不自动续跑。
- 5210b49核对（代码差异及原生事件）：父提交的保真复核已含targets、original_judgments和按location过滤的context_segments；本次只为选择器补齐后两项并复用输入，未改变保真输入或门槛。第二十三笔丢失效率数值，第二十四笔保留数量却不能表达威胁边界，不能统称丢数字，也不能仅凭上下文送达归因为模型能力或门槛过高。已对照两笔原生请求和保真结果核实；详细调用关联保留在内部artifacts。
- 复验盘点：片段ID抽取（第二十一笔）、JSON模式/selected_quote绑定、QS准入优先及ConnectError重试（第二十二笔）、S4说明进入抽取（第二十三笔）、数字/条件保留提示（第二十四笔）均已触发，不等于验证有效；选择器上下文补齐已在第二十五笔确认送达，但仍有选择失败；第二十六笔已执行S4新增说明后的语义复核和评分优先分支，完整评分/纳入闭环仍未完成。服务端strict JSON Schema曾真实传输但未约束住超长值，现已移除，不列为有效机制；历史“未付费复验”是当时状态。
- 历史执行状态核对（第二十五笔运行前）：第二十四笔当时是最近一次已记录的真实运行；选择器上下文补齐后的下一笔仅完成准备，尚无原生运行状态，不算已执行。详细请求、响应和调用关联保留在内部artifacts供分析，不纳入对外变更记录。本次仅核对并更新记录，未付费运行或更改契约；下一步在获授权的新workspace验证选择器输入及语义结果，unclear可恢复性仅作观察，不据两次失败放宽守卫。

- 第二十四笔15/64次、140/1200秒、136379 tokens，原生4/8；inputs_and_outputs纠错选from 1.5 million Bell pairs，实验数量无法表达威胁边界，保真unclear触发error/contract_violation，本笔未到Track/评分。运行后让选择器与保真复核复用原始判断及受影响页正文，不增长提示、不改50字符/一次纠错；原失败回放仍拒绝，3项守卫回归通过，输入补齐未付费复验。

- 第二十三笔31/64次、226/1200秒、414848 tokens，原生8/8；QS S1/S2=true，S3反证原引含省略号，纠错选成detection efficiency丢失数值，保真unclear触发error/contract_violation。S4新增说明首次进入真实抽取请求，候选true尚未复核，未评分；保留历史判定。已有34字符原文数值选项，选择指令原位改为保留关键数字/单位/否定/条件；本地结构/接地回放和3项守卫回归通过，不改50字符、一次纠错或保真守卫，修改未付费复验。
- 第二十二笔DIQKD单案例32/64次、269/1200秒、367307 tokens，原生8/8；QS优先调度及ConnectError一次重试真实触发。QS true/true/true/false，completed/case_coverage_complete，未评分；S4已收到require_fault_tolerance=false却以实验室/扩网未工程化判false，不能作可靠语义拒绝。运行结束后才新增prompt_rule统一解释该条件，第二十二笔抽取/复核请求均不含新增description；4项相关离线回归通过，不改YAML、历史判定或守卫，澄清待首次真实验证。
- 增加可选preferred_track调度偏好，默认不变；先执行指定Track当前就绪的准入/评分，避免另一Track拒绝提前结束案例。八字段前置、准入全true评分及覆盖停止契约不变；6项相关离线回归和新案例doctor通过，真实效果待新笔验证。
- 第二十一笔37/64次、307/1200秒、345375 tokens，原生8/8；片段ID抽取真实触发。QS准入true/false/false/true，NLC true/缺证/false/true（C2错句拒绝）；completed/case_coverage_complete完成QS拒绝分支及确定性自检，未调度评分，不等同语义/真人验证，不续跑。
- 第二十笔后修复：ContextGem抽取改选逐句预列的≤50字符原文片段ID，客户端展开后仍经原引用/接地/双审；删除自由抄引/数字符提示，不加请求或纠错。保存正文的离线选择夹具通过映射/接地，错句、未知ID及自由文本仍拒绝；15项相关回归通过，真实模型选择效果待新笔复验。
- 第二十笔移除服务端Schema依赖后原生执行21/64次、161.8/1200秒、310094 tokens，7/8 FILLED；本地超长项隔离真实触发。唯一缺real_world_problem（首轮77字符、后续错句），固定来源缺口停止operational_pool_exhausted，未调度Track/评分，不自动续费。
- 移除抽取对服务端strict Schema/maxLength的依赖及专用封装，恢复ContextGem原生数组；保留本地50字符、逐项隔离、引用/接地与双审。第十九笔响应离线回放仅拒52字符项，6项通过引用映射、1项仍引用不匹配；必要回归27项及5个子用例通过，doctor ready，未付费复验。
- 第十九笔保留实际HTTP请求/响应：1/64次、22.6秒、19409 tokens；strict Schema/maxLength=50逐字传输，HTTP200响应real_world_problem短引仍52字符。运行级守卫在双审前停止（原生error/contract_violation，新workspace 0/8），未到Track；skill运行代码未改，不续跑。
- 第十八笔启动前doctor漏传Document导致TypeError（正文/模型调用0），已补齐并自检ready；唯一真实invocation为13/64次、86秒、原生3/8。请求记录strict Schema/maxLength=50但响应3条超长，按新阻塞主动中止（原生user_aborted/CancelledError），未到Track，不自动续跑；客户端实际传输与服务执行边界待核对。
- 第十七笔后离线修复：OpenAI兼容抽取发送复用现有字段类型/短引上限的原生JSON Schema，删重复quote Schema提示；保留原始响应及后置守卫，结构化请求被拒即停，不删参数重试。保存响应离线重放仍拒6条违规值；选错引用句保留拒绝，服务支持及实际效果未付费复验。
- 第十七笔简化基线25/64次、205秒原生6/8，缺real_world_problem（超长后引用句不含短引）和existing_practice（high置信度后短引超长），固定来源缺口停止，未到Track；5次反证纠错通过结构/接地/绑定复核，抽取规则共享及解析去重已真实触发，不证明成功率提高，不续跑。
- 第十六笔12/64次、177秒原生5/8；量子机制引用句不含短引，后续success_criteria归属调用超时，以error / TimeoutError停止，不重试，未到Track。运行后局部去重：公共抽取规则8份改1份、JSON解析归契约模型、删重复绑定检查；保留50字符及现有守卫，简化未真实复验。
- 历史验证状态（截至第二十四笔）：片段ID选择、JSON模式、selected_quote绑定及QS准入调度偏好均已有真实触发；S4新增说明在第二十三笔进入抽取，其语义复核与评分优先分支未执行。数字/条件保留提示已有第二十四笔触发，但仍因威胁边界含义不足被拒；选择器上下文补齐待复验。结构/接地/绑定通过不等于语义正确；词序号范围旧方案已被替换，不计为并存待验证机制。
- ConnectError自动重试已在第二十二笔触发一次并成功；抽取锚点/quote Schema说明及归属章节职责提示已有第十六笔触发，但该笔超时，不能认定普遍修复。下列各笔“未付费复验”描述的是当时状态，不代表当前全部仍未验证。
- 第十五笔24/64次、190秒原生6/8，缺real_world_problem和existing_practice；首段7条抽取短引超长被拒，后续现实问题归属以结论段/字段语义弃判，未到Track。3次复核已逐字绑定，但仍见supported与理由否定不一致；补抽取锚点及现有quote JSON Schema说明、归属不以章节代替身份判断的提示，候选修正未付费复验，原判定不改。
- 第十四笔25/64次、177秒原生7/8，缺existing_practice（短引同时命中摘要和正文两句），固定来源缺口停止，未到Track。JSON复核4次合约接收，但一项选this却解释原拒绝引文；增加selected_quote逐字绑定并澄清复核对象，候选修正未付费复验，不改历史判定。
- 第十三笔15/64次、137秒原生5/8；55字符反证经ID选成43字符连续原文（含换行；修正先前误记42）并通过结构/接地，随后语义复核返回说明加JSON而契约拒绝，未到Track。该复核对OpenAI兼容传输启用请求级JSON模式并审计参数，保持完整响应校验、无额外纠错；候选修正未付费复验。
- 第十二笔17/64次、137秒达到原生7/8，缺real_world_problem；固定来源缺口停止分类真实生效，重试及片段ID未触发。量子机制值外推非对称延迟安全，judge已见互易性限制仍supported；补逐项主张与威胁范围提示，候选修正未付费复验。
- 按用户新授权，正文ConnectError在原预算内自动重试一次（间隔1秒，累计最多2次尝试）；保留失败与重试回执，429/超时不重试，模型SDK重试0。
- 第十一笔PDF连接失败（ConnectError），0次模型调用、约1秒、0/8，片段ID及Track未触发；原生误记预算耗尽。修正固定URL打开失败立即error/source_unavailable，保留原回执且不重试。
- 第十笔16/64次、128秒达到6/8（含existing_practice），一段纠错45字符通过长度、另一段仍61字符且越过显式终点；未到Track。纠错改为选择预先校验的原文短片段ID，保留绑定/接地/同一反证语义复核及一次纠错，尚未付费复验。
- 第九笔6/64次、83秒达到1/8；模型选定范围仍超长（含原55字符范围），未到Track且未触发语义复核。原文词表补按原始空白计算的最远合法终点，超长拒绝/一次纠错/同一反证复核不变，尚未付费复验。
- 第八笔16/64次、163秒达到5/8；quantum_mechanism_role反证109字符纠错后57字符仍违规，未到Track。超长纠错统一为原文范围选择及同一反证语义复核，不增加纠错次数；修复未付费复验。
- 第七笔21/64次、152秒达到7/8，缺existing_practice，未到Track；3次范围纠错通过结构/接地，但一处有威胁含义偏移；固定来源已处理被原生误报为预算耗尽。
- 范围选择后增加同一反证语义复核请求（计semantic预算、无纠错）；固定来源处理完且缺证改为有据的操作范围耗尽。修复尚未付费复验，历史回执不改。
- 第六笔7/64次、57秒停于constraints非原文短引原样回传；本笔1/8，未到Track。超长纠错及根数组外壳分支均触发通过；非原文纠错改为模型选择原文词序号范围，原始空白/50字符/绑定/全部判断守卫保留，尚未付费复验。
- 第五笔13/64次、130秒在success_criteria反证引文连续两次改写后停止，八字段4/8，未到Track；将有效位置上的非原文短引纳入同一次定点纠错，其他判断不变、合并后仍全量接地，尚未付费复验。
- 第四笔26/64次、283秒达到八字段8/8；55字符定点纠错通过（未触发根数组外壳分支），NLC接收C1=true/C4=false，但C4理由混用C3/C4，不能作可靠拒绝；QS回退抽取契约失败，评分未调度。
- 将每字段规则放入对应ContextGem概念，区分序列ID与领域字段名；judge明确按目标规则核对真假，回退明确引用对象和原样段落位置。提示修正未付费复验，历史原件保留。
- 第三笔18/64次、183秒停于定点纠错根数组缺replacements外壳；本笔5/8、未到Track。随后补无损外壳处理，原响应/条目内容及全部证据守卫保留。
- 首笔13/64次停于55字符纠错；复验36/64次、315秒推进到八字段完整和两Track部分准入，4次定点短引纠错通过；评分未调度，USD未知。
- ContextGem换行粘词修复在本次正文抽取中推进；单文档不代表多文档提取顺序普遍解决；全部原始回执保留。
- 新阻塞为C2超长短引和C3将缺证输出为空引文候选；准入结构收紧为true/false且covered，明确缺证返回空items，仍保留50字符拒绝、不加纠错；修改未付费复验。

## v20 — 2026-10-16

- 将辅助说明、历史变更、非核心测试和6个独立辅助入口移入本地 archive/；活跃规则合并至证据、流程、批次契约，archive/ 加入 Git 忽略。
- 保留在线实际依赖、配置、接地和既有短引/映射/归属修复；归档改变执行文件集合，新运行使用全新 workspace。
- 真实单案例仍以最后实际回执为准；整理与离线通过不代表 Track 跑通。v19及更早原件在 archive/v19/。
# 2026-10-22

- DeepSeek Search/Fetch pilot: after removing proxy variables and consolidating configuration, the run completed with 3 opened sources and 24 model calls, stopping at `analysis_limit_reached`; 3 evidence cells filled, 5 uncertain, 19 missing, and no admission/score was triggered. The saved run is `artifacts/quantum-scout/workspaces/pilot-workspace-deepseek-20261022-final3`.
- DeepSeek pilot rerun with `analysis_limit=12` reached 5 discovered and 2 opened sources before stopping on an extraction schema error (`LLMExtractionError`) after 21 model calls; 1 candidate was extracted, the problem definition remained incomplete, and admission/score did not run. Saved at `artifacts/quantum-scout/workspaces/pilot-workspace-deepseek-20261022-analysis12`.
- The extraction bridge now states the required top-level ContextGem array shape with an explicit example; singleton object responses remain rejected rather than being assigned to an arbitrary field.
- The extraction prompt now requires non-empty paragraph/sentence references on every candidate and instructs the model to return an empty item list when it cannot cite evidence; ungrounded candidates remain fail-closed.
