# SearchOS 复用边界与能力矩阵

Quantum Scout 使用 SearchOS 组件，不运行原版 Orchestrator、SearchSession 或浏览器工作流。
在线唯一可写事实源为 `state/quantum_adapter.json`；领域 adapter 是唯一状态所有者。
SOCM、Frontier、EvidenceGraph、coverage map 和 calibration 导出均从已提交事实重建，不能反写事实。

## 允许的组件接入

- searchos_configuration 只读 WebSettings、web_overlay.store/apply_to_runtime/reload_settings_in_place；不调用会写回或迁移共享配置的启动器。
- 在线模型经 resolve_profile/get_model_for；搜索经 resolve_search_provider_name/build_search_provider，不另造后端选择器或搜索 SDK。
- adapter 使用 SearchState/CoverageMap/Frontier/EvidenceGraph/StrategyMemory 及相关数据类型。
- SkillRegistry、run_executor/ExecutionPolicy 用于领域接地 access skill；事实始终为空，接地候选须另行双审。
- WorkspaceManager 仅在 adapter.prepare/persist 内写派生目录。persist 先验证投影，再提交 adapter 事实，然后写投影；repair 从已提交事实恢复。

原版 SearchSession/Orchestrator 不得打开本 skill 的同一 workspace；不能导入它们独立改写的状态，
不能从 SOCM 文件读取额外事实补入 adapter。外部直接编辑派生状态会被 repair 覆盖，不视为事实变更。
运行进程由 single_runner 排它，事实更新由 adapter.locked 保护；在线配置固定后不再 add-case。
第三方绕过锁直接写文件不受本地代码控制，禁止把这种写入当作受支持的集成方式。
doctor 的 searchos_runtime_enabled=false 是本入口架构说明，不是宿主进程监控结论。

## 版本与升级

项目固定 SearchOS 0.1.0、ContextGem 0.27.0，完整解析依赖用 uv.lock，源码修订与安装路径写 runtime manifest。
同版本号源码变更仍属升级，不能只比较版本字符串。私有接入集中在 searchos_configuration、searchos_network、
searchos_adapter 三个边界模块；这些组件目前没有稳定公共 API 保证，不宣称无漂移风险。
升级先在独立配置/目录重验 provider 选择、模型角色、执行器隔离、SOCM 序列化/repair、Frontier 容量、
ContextGem 引用映射/候选拒绝/逐请求预算和错误路径。离线通过不等于真实服务或语义正确。
不能为升级补写旧 workspace 基线；新执行用新 workspace，旧执行使用归档依赖与 skill。

## 能力矩阵

“可替换”表示架构上可评估，不代表现在要新增另一套实现；选择以状态所有权、审计绑定、停止契约和领域规则为准。

| 功能 | 复用来源/边界 | 状态所有者 | 替换判断 | 固定方式 | 验证 |
|---|---|---|---|---|---|
| 模型配置/客户端 | SearchOS profiles/models | SearchOS 配置；adapter 保存调用事实 | 继续复用 | 依赖锁+源码修订+设置哈希 | doctor、配置/预算契约 |
| 搜索 provider | SearchOS factory | SearchOS 配置；adapter 保存结果/失败 | 继续复用，不并行造选择器 | 同上 | 配置矩阵、HTTP 故障、可选真实探针 |
| 抽取/句子引用 | ContextGem + 薄桥接 | adapter | 继续复用 | 依赖锁+源码修订 | 引用映射、拒绝、降级、预算 |
| 隔离执行器 | SearchOS runtime executor | adapter 接收候选 | 继续复用 | 依赖锁+执行基线 | 禁网/超时/回执 |
| SOCM/coverage | SearchOS 数据类型 | adapter，派生可重建 | 可替换视图 | 依赖锁+执行基线 | 序列化、repair |
| Frontier/EvidenceGraph | SearchOS 组件 | adapter，派生可重建 | 可替换调度视图 | 同上 | next/release/capacity、冲突 |
| 领域证据/双审 | 本地 review_policy | adapter | 保持领域实现 | 执行基线 | 绑定、四条件、反证位置/短引 |
| 接地 | 本地 executor | adapter | 保持受限字符串门 | 执行基线 | 原文跨度、格式白名单、语义变化负例 |
| 覆盖停止/审计 | 本地 coverage/audit_policy | adapter | 保持领域实现 | 执行基线 | 逐案例重算及自检、batch guard |
| claim ledger | 本地，参考 DeepDive 思路 | adapter 事件 | 暂无必要引入数据库流水线 | 执行基线 | ledger 追溯 |
| 优先队列 | 本地启发式，参考 ASReview | adapter 事实/派生 Frontier | 暂无必要训练分类器 | 执行基线 | 调度回归 |
| 引用身份 | 本地四服务 adapter | adapter | 只调用显式 allowlist | 执行基线；远端 API 不可本地锁定 | 标识矩阵、注入响应、可选真实探针 |
| 导出/成本/基线 | 本地领域协议 | adapter；导出为派生 | 保持领域实现 | 执行基线+文档摘要 | export/render/guard、成本未知值、恢复拒绝 |
| 沙箱 | 宿主执行设施 | 宿主 | 环境能力 | 环境回执 | 独立探针、受限执行 |

DeepDive、ASReview、QuantumNovelty 仅作设计参考，不引入其完整运行时或双重状态。
academic-research-skills 参考四索引及标识/标题核对原则，客户端因 CC BY-NC 4.0 和请求契约不兼容未直接引入；详见 [四服务复用评估](citation-identity.md)。
scientific-agent-skills 仅参考 metadata.version 约定；无运行依赖。
扩大基础设施复用以当前契约满足为条件，不为了功能列表完整而启用上游整个研究循环。
