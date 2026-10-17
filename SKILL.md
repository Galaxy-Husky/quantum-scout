---
name: quantum-scout
description: 搜索驱动的量子应用证据发现；检索论文、专利、报告和白皮书，抽取、接地、双审、准入及评分并导出可追溯案例，支持查询已有 SQLite 数据。不用于理论推导、HFT 或 defense 场景。
---

# Quantum Scout

推进真实搜索链路；先修阻塞，再在授权预算内验证，不以文档或离线测试通过代替真实结果。

## 按需读取

| 任务 | 权威入口 |
|---|---|
| 搜索、打开正文、调度与恢复 | [执行流程](references/workflow.md)；`scripts/searchos_online.py doctor/run/open-source` |
| 八字段、来源资格、短引、双审与评估语义 | [证据协议](references/evidence.md) |
| Track 条件、评分参数及领域范围 | `config/tracks.yaml`、`config/exclusions.yaml`、`config/scope.yaml` |
| 导出、checkpoint、覆盖与停止状态 | [批次契约](references/batch-schema.md) |
| 已有 SQLite 查询 | 只读连接执行 `references/queries.sql`，不启动搜索 |
| 框架复用与组件职责 | [复用边界](references/workflow.md#框架参考与复用边界)、[职责划分](references/workflow.md#代码模型与持久化的职责) |
| 修改组件或验证修复 | [修改与验证](references/workflow.md#修改与验证) |

已知 PDF/HTML URL 直接 `open-source`，不先搜索；产物放项目 `artifacts/quantum-scout/`，用 `--project-root` 指定项目。默认 calibration；production、阶段转换与正式复盘须明确授权。

## 硬边界

- 整个 skill 的执行与修改均遵守[节约规则](references/workflow.md#代码模型与持久化的职责)，减少调用和输入；按需读取，不预加载全部参考材料。

- 付费调用逐笔授权，固定输入、预算与全新 workspace；不自动续费，不把剩余额度当重跑授权。服务失败及重试按[执行流程](references/workflow.md#配置和调用)处理。
- 不用摘要或推断补证，不预填准入或分数，不放宽短引、接地、双审与评分门槛；具体定义只在上述权威文件维护。
- 在线事实只来自 `state/quantum_adapter.json`，派生视图不能反写事实；所有权与恢复见[状态契约](references/workflow.md#状态导出与兼容)。
- 先单案例，再多案例，最后引用扩展/S2；如实保留缺证、未执行和失败，不把 agent 核对称作真人抽查。
