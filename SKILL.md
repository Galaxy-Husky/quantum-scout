---
name: quantum-scout
description: 搜索驱动的量子应用证据发现与合规审计；检索论文、专利、技术报告和白皮书，抽取、双审、评分并可追溯导出案例，支持查询已有 SQLite 数据。不用于理论推导、HFT 或 defense 场景。
---

# Quantum Scout

> 本文件维护入口选择与执行层级；证据、流程、停止和审计契约由下列引用分别维护。

通过自动检索、抽取、双审校验与可追溯导出识别量子现实应用案例。领域规则以 `config/tracks.yaml`、
`config/exclusions.yaml` 和 [证据协议](references/evidence.md) 为准。
在线 workspace 的 `state/quantum_adapter.json`是唯一权威事实源，SOCM 是可重建的派生视图。
SQLite 是 production 主数据源，`cases/<case_id>/evidence.md` 是审计快照；
calibration 只生成批次 JSON、checkpoint、comparison 和可选单案例草稿。

定位目录与脚本职责时，查阅 [文件树与职责](references/file-map.md)；修改上游接入时查阅 [SearchOS 边界与能力矩阵](references/searchos-boundary.md)。
配置引用身份核验时，查阅 [四服务契约与复用边界](references/citation-identity.md)；默认关闭，不以元数据代替正文证据。
修改或验证实现时，查阅 [测试边界与分层验证](references/testing.md)；含按模块、CLI 与子进程范围分类覆盖率缺口的只读工具，不以离线通过替代语义质量验证。
规划改进或评估 Pilot 时，查阅 [工程门禁与真实服务验证](references/pilot-validation.md)：
P1 离线门禁必须通过；真实服务未验证单独披露，不阻塞 Pilot，不自动触发阶段转换。

## 入口与执行边界

- 查询已有数据：只读执行 `references/queries.sql`，不启动搜索。
- 搜索/评估：读 `config/*.yaml`、[流程](references/workflow.md)、[来源缓存](references/source_cache.md) 与 [批次契约](references/batch-schema.md)。默认 pilot / calibration，准备后继续执行至有据可查的终止条件。
- 在线为已知候选补证：读 [在线入口](references/searchos-online.md)，使用 `searchos_online.py doctor/run/open-source`；模型与搜索后端复用 SearchOS 共享设置，任务仅配置候选、查询和预算。已知正文 URL 使用 open-source，可显式传 --expected-title；预算与一次恢复边界见在线入口，调整调用量或容量前查阅 [限制与预算](references/limits.md)。
- 离线 SOCM 适配与复核导入：读 [接入协议](references/integration.md)。`searchos_adapter.py` 管理事实和派生状态，`schema_generator.py` 从领域配置生成策略；不自主新增案例。

production、阶段转换、正式复盘需用户明确确认。生成产物集中到项目的
`artifacts/quantum-scout/`，用 `--project-root` 指定项目；[审计层](references/audit-layer.md) 维护路径、反证、引用身份、成本和自检协议。
显式建空生产库用 `scout_db.py create-schema --workspace <路径> --mode production`；建库不等于启动搜索。

## 约束执行层级

| 约束 | 层级 | 执行者 |
|---|---|---|
| 引文存在性与原文定位 | code | assets/quantum_grounding/executor.py、在线位置核对 |
| attributed + supported + location_checked + domain_rule_met | code | review_policy.supported_pair |
| 复核绑定、不同 reviewer ID、反证结构 | code | review_policy、adapter |
| 同案例同 Track 覆盖链 | code | coverage_policy |
| 覆盖链自检、正文哈希及审计阈值 | code | audit_policy、stop_decision、导出守卫 |
| 人工审计状态 | label | audit-attribution --post-hoc；不阻塞停止 |
| 停止契约 | code | validate_completion_guard |
| 总预算与并发锁 | code | BudgetEnd、single_runner |
| 引用扩展深度/cap、identity 三态 | code | add_citation_results、citation_backends |
| 部分处理警告 | code | export_batch |
| layer1→2→3 来源优先级 | observed | agent；发现轨迹与 opened_order 可供核对 |
| 停止判断、每轮调用及中断 | observed | online.events |
| HFT/defense 等领域排除 | judgment | agent |
| 八字段语义、Track 准入、三态归属 | judgment | agent / judge |
| 实际场景、任务、参与方三要素去重 | judgment | agent |

code 校验已记录的结构与绑定，不保证语义正确或真人身份；judgment 需要实质判断；
observed 记录行为供复盘，不表示顺序策略已被强制执行。不同 reviewer ID 不保证模型误差独立。

证据资格、缺证处理、来源独立性和禁止推断补证统一见 [证据协议](references/evidence.md)。
领域排除以 `config/exclusions.yaml` 为准。

## Track 与运行结果

两条 Track 独立判断；领域条件及维度规则见 `config/tracks.yaml`，
问题定义前置门、准入/评分顺序与归一化见 [流程](references/workflow.md#准入评分抽取)。
`display_track` 只控制展示；来源与案例保留多对多关系。

停止值、完成标志和举证条件统一见 [停止契约](references/batch-schema.md#停止契约当前版本)。
每批正文打开后更新 checkpoint/comparison 并继续；报告展示停止原因、能力边界及缺口。
覆盖停止不表示准入、评分达标或全局证据充分。版本演进与历史审计入口见 [CHANGELOG](CHANGELOG.md)。
