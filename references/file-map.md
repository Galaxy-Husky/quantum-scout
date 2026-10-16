# 文件树与职责

本文用于定位文件；规则与接口以对应文档为准。树中的 `test_*.py` 为测试文件的合并表示。

```text
quantum-scout/
├── SKILL.md                         # 使用入口、执行边界与文档导航
├── CHANGELOG.md                     # 变更记录及历史兼容说明
├── config/                         # 领域配置与数据库结构
│   ├── tracks.yaml                 # 两条 Track 的准入条件与评分维度
│   ├── exclusions.yaml             # 排除领域与匹配规则
│   ├── scope.yaml                  # 阶段范围、上限及审计配置
│   ├── search-strategy.yaml        # 搜索策略与种子查询
│   └── schema.sql                  # production SQLite 表与约束
├── references/                     # 按需读取的规范与操作说明
│   ├── file-map.md                 # 本文件：目录与脚本索引
│   ├── testing.md                  # 测试保障边界、分层验证与结果口径
│   ├── pilot-validation.md         # 两级门禁、优先级、可选实测与运行期审计模板
│   ├── workflow.md                 # 搜索、问题定义、准入、评分与入库顺序
│   ├── evidence.md                 # 证据资格、字段语义、案例归属与来源角色
│   ├── batch-schema.md             # 批次 JSON、checkpoint 与停止契约
│   ├── audit-layer.md              # 反证、自检、人工审计、成本与基线追溯
│   ├── searchos-boundary.md        # 上游 API、状态所有权与能力矩阵
│   ├── searchos-online.md          # 在线配置、CLI、预算与恢复
│   ├── integration.md              # 离线适配器接口与复核记录导入
│   ├── source_cache.md             # 来源缓存身份与更新
│   ├── review.md                   # 阶段人工复盘与分支调查
│   └── queries.sql                 # 已有生产数据的只读查询
├── scripts/                        # 执行入口及共用策略模块
│   ├── searchos_online.py          # 在线入口：doctor / run / open-source
│   ├── searchos_configuration.py   # 只读接入 SearchOS JSON、环境与配置来源追溯
│   ├── searchos_adapter.py         # 管理本地事实、复核导入及 SOCM 派生视图
│   ├── searchos_project.py         # 项目/工作区路径、初始化与运行环境快照
│   ├── schema_generator.py         # 从领域配置生成 SearchOS 表与策略技能
│   ├── scout_db.py                 # 显式创建 production 数据库结构
│   ├── download_source.py          # 下载单个公开来源并保存来源清单
│   ├── searchos_network.py         # 有界搜索、正文下载与 PDF/HTML 分段
│   ├── contextgem_extractor.py     # ContextGem 抽取桥接与候选引用映射
│   ├── citation_backends.py        # 四服务身份核对、回执缓存与引用元数据扩展
│   ├── validate_grounding.py       # 本地调用字符串接地门并保存失败
│   ├── claim_ledger.py             # 候选主张、原文跨度及反证线索账本
│   ├── review_policy.py            # 归属、语义、位置及复核绑定守卫
│   ├── coverage_policy.py          # 同案例同 Track 覆盖重算与导出守卫
│   ├── online_policy.py            # 在线停止举证、分段进度与归属统计
│   ├── audit_policy.py             # 机器自检、人工抽查阈值与案例标签
│   ├── cost_policy.py              # 调用分类、token 与成本账本
│   ├── baseline_policy.py          # skill 内容哈希与跨基线恢复检查
│   ├── field_diagnostics.py        # 从记录派生字段、表与来源缺口诊断
│   ├── audit_reachability.py       # 只读统计近期分支观察与待调查项
│   ├── export_batch.py             # 将已复核事实导出为校准批次
│   ├── validate_batch.py           # 批次结构、准入一致性及停止契约校验
│   ├── classify_source.py          # 按案例证据贡献判定来源角色
│   ├── render_calibration.py       # 渲染批次报告与单案例草稿
│   ├── check_searchos.py           # 离线检查 SearchOS 适配与隔离执行器
│   └── check_project_environment.py # 离线检查抽取/检索环境
├── assets/                         # 运行时使用的模板与 access skill
│   ├── searchos.env.example        # 模型/检索环境变量模板
│   └── quantum_grounding/
│       ├── skill.md                # 字符串接地 access skill 说明
│       ├── manifest.yaml           # access skill 注册信息
│       └── executor.py             # 确定性引文匹配与定位回执
└── tests/
    ├── test_*.py                   # 契约/流水线回归、真实解析器及受控故障
    ├── review_fixtures.py          # 共用的构造复核数据
    ├── offline_benchmark.py        # 本地合成文档/多案例/多来源资源基准
    ├── historical_contracts.py     # 历史批次只读兼容与字段引用标签统计
    ├── coverage_inventory.py       # 哈希绑定的覆盖率模块/CLI 分类与子进程调用点清单
    ├── live_api_contracts.py       # 显式预算的可选真实 API 探针，默认不收集
    └── live_attribution_regression.py # 可选真实归属回归，会消耗 API 额度
```

查找运行入口时，从 [在线入口](searchos-online.md) 或 [离线接入](integration.md) 开始；
核对判定规则时，按上面的职责定位规范和策略模块。

研究产物位于项目的 `artifacts/quantum-scout/`，其目录布局见
[审计层的统一产物路径](audit-layer.md#统一产物路径)。

四服务选择/许可及回执契约见 [citation-identity.md](citation-identity.md)。

限制及调整依据：`references/limits.md`；四服务身份策略和密钥位置：`references/citation-identity.md`。

`scripts/searchos_seeds.py`：无网络解析 layer1 的显式正文 URL / 普通 Web 查询，供 agent 规划使用；不自动启动在线 runner。
