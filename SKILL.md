---
name: quantum-scout
description: 搜索驱动的量子应用证据发现；检索论文、专利、报告和白皮书，抽取、接地、双审、准入及评分并导出可追溯案例，支持查询已有 SQLite 数据。不用于理论推导、HFT 或 defense 场景。
---

# Quantum Scout

目标是推进量子应用案例的真实搜索链路。先修复阻塞点，再在授权预算内继续执行；不设独立付费诊断阶段，不以文档或测试通过代替真实结果。

## 执行入口

- 搜索与已知来源补证：读 [流程](references/workflow.md)，使用 `scripts/searchos_online.py doctor/run/open-source`；已知 PDF/HTML URL 直接 `open-source`，不先调用搜索。
- 字段含义、来源资格、引文及双审：读 [证据协议](references/evidence.md)；领域条件以 `config/tracks.yaml`、`config/exclusions.yaml`、`config/scope.yaml` 为准。
- 导出、checkpoint、覆盖与停止：读 [批次契约](references/batch-schema.md)。
- 已有 SQLite 查询：用只读连接执行 `references/queries.sql`，不启动搜索。

在线唯一事实源为 workspace 的 `state/quantum_adapter.json`；SOCM 与 calibration 是派生视图。产物集中到项目 `artifacts/quantum-scout/`，用 `--project-root` 指定项目。production、阶段转换与正式复盘须明确授权；默认只做 calibration。

## 执行约束

1. 只用实际打开的正文，不用元数据、搜索摘要或推断补证。每项先字符串接地，再分别判断案例归属、语义、位置及领域规则。
2. 八字段前置门满足后才做 Track 准入。C1–C4 / S1–S4 保留 true/false/insufficient_evidence；该 Track 全 true 才评分，不预填分值。
3. 付费调用逐笔授权，固定输入、预算与全新 workspace；剩余额度不授权重跑，不自动续费。429/超时后停止该服务，不循环刷成功。
4. 保持50字符短引、最多一次共享格式纠错、SDK重试0；不截写原引文、不放宽接地、不把发现的反证改报 false。
5. 单格 FILLED 不等同语义正确；多案例停止逐案例重算，不能跨案例/Track拼接。不同 reviewer ID 或相同模型的两次调用不保证误差独立。
6. 先完成单案例，再做多案例，最后做引用扩展/S2；保持缺证和未执行的真实状态。

## 修改与验证

保留实际执行所需的模块依赖；`schema_generator.py` 直接读取证据协议的八字段表，不得移走或改坏该表结构。模型/搜索复用 SearchOS 共享设置，不写回共享配置，不并行启动原版 SearchSession/Orchestrator 写同一 workspace。

修改组件后只跑相关回归，再用获准预算重跑真实链路。离线用例可用替身，但不能冒充真实模型或真人抽查；覆盖率数字不设执行门槛。使用项目解释器，例如：

```sh
PYTHONPATH=skill/scripts:skill/tests .venv/bin/python -m pytest -o pythonpath=src skill/tests -q
```

`tests/test_workflow_contracts.py` 是集成回归；其余活跃测试仅保留在线夹具、ContextGem映射、短引纠错与归属上下文回归。历史文档、其余测试和独立诊断工具已移入 `archive/`，不在默认阅读、测试或运行路径中；需要时先恢复到独立副本并核对依赖。

每轮只交代实际动作、预算、阻塞点、修复/重跑结果和下一步唯一动作。原始请求/响应与失败回执仍由原生运行日志保存，不另建平行分析体系。归档不改变历史 workspace；执行文件集合变化后必须新建 workspace。
