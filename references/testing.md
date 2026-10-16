# 测试边界与分层验证

> 本文件唯一维护测试定位、验证分层与结果表述；运行规则仍由各自 owner 维护。

## 能证明什么

Quantum Scout 的测试验证输入契约、边界守卫、状态流转、故障安全和可追溯输出。
离线替身适合确定性门禁；不要求人工 golden set，也不承担模型准确率训练。
真实模型归属错误、语义支持误判与反证遗漏仍是系统风险。人工抽查是独立事实记录，
agent 不得冒充真人；离线合成 human 夹具仅限可丢弃测试，不能导入真实 workspace。
置信度规则见 [证据协议](evidence.md#记录格式)，审计三层与反证保障边界见
[审计层](audit-layer.md#审计实现分层)。不得将声明完整误报为实际搜索充分。

在线先校验 Candidate 再接地，之后执行双审；投影还检查绑定、来源资格及同格值冲突。
单格 filled 不以整条 Track 覆盖完整为前提；coverage_witness 服务于案例级覆盖/停止，
不能倒置为单格填充条件。冲突聚合比较通过守卫的候选值，不等于理解全部语义矛盾。

停止契约、双审绑定、接地校验、基线保护、作用域隔离均有测试用例，
不据此声称“全覆盖”。异常用例占比未经统计，不报告百分比或确定的正常场景占比。
实测覆盖率须说明版本、执行命令、纳入文件、分母及子进程是否计入；行/分支覆盖不等于语义正确。

## 分层执行

| 优先级 | 验证 | 记录边界 |
|---|---|---|
| 条件项（非离线门禁） | 真实搜索、引用身份及真实文档/模型全链路 | 保存回执；条件不足标未验证，不阻塞 Pilot；不主动制造服务端限流 |
| P1 | 真实 PDF/HTML 解析引擎处理本地合成文档 | 验证正文位置与接地；不等同真实服务链路验证 |
| P1 | 三源以上、多轮增量、缓存/游标恢复与停止 | 受控序列与真实运行分别报告；合成响应只能证明流水线行为 |
| P1 | online / SOCM / batch / render 一致 | 比较共同事实和相同口径；原始候选数不等于填充数，视图无需相同结构 |
| P1 | 双审分离、反证结构与范围、置信度标签 | 复用现有守卫；验证合法标签流转与非法输入拦截，不新增置信度门槛 |
| P1 | 极端配置、provider/backend 组合、渲染完整性、人工导入 | 区分配置合法、受控传输通过与真实服务通过；合成人工数据仅用于可丢弃 workspace |
| P2 | 文档/模型/网络故障与部分失败 | 验证拒绝、有限恢复、状态完整性；终止为 error 可以是正确结果 |
| P2 | reachability、doctor、CLI | 只读扫描、诊断信息、退出码与输出契约；无观察只表示待调查 |
| P2 | 长文档、多案例、多来源基准与置信度分布 | 记录环境、测量范围及标签口径；基准不是资源上限保证 |
| P3 | 并发容量压测 | 不作为 Pilot 门禁；低成本排它与异常释放回归可提前执行 |
| P3 | 历史回归与覆盖统计 | 保留旧基线与历史快照，不自动迁移，不按未触发删除分支 |

新验证用独立配置、独立 workspace 与固定 skill 基线，保持生产配置不变。
真实请求只用公开接口或已配置的凭据；有限预算，失败如实保留，不借用公开泄露密钥。
探测遇到限流后暂停该服务的后续验证，报告受阻；不靠循环重试获得通过结果。
真实来源的负例、冲突和准入结果不预设；合成守卫用例可构造非法输入，必须明确标为离线测试。
不为获得填充/评分结果编造证据。未实际人工抽查保持 unverified，不填写虚构 check。
默认离线测试在每例前清除操作者的 API 密钥环境变量，单例可显式注入假密钥；真实探针不经此 fixture。

## 执行与验收

在已安装项目依赖的环境执行（将 `<skill>` 替换为冻结副本的路径）：

```sh
PYTHONPATH=<skill>/scripts:<skill>/tests python -m pytest -o pythonpath=src <skill>/tests -q
# 若安装了 coverage，可用相同范围分别测量修改前后：
python -m coverage run --branch --source=<skill>/scripts,<skill>/assets/quantum_grounding -m pytest -o pythonpath=src <skill>/tests -q
python -m coverage json -o coverage.json
```

命令使用项目解释器；coverage 是可选测试工具，不是 skill 运行依赖。默认收集不含 CLI/隔离执行器
子进程，需在报告中说明，不能把父进程未执行算成全局不可达。
真实测试结果和耗时基准放在项目 `artifacts/quantum-scout/validation/`，不写成永久规范中的通过结论。

校准阶段只到 batch 导出与渲染；SQLite 是另一个生产阶段，不计入四视图一致性。
失败原因、审计标签等只在实际提供这些指标的视图间比较；报告必须区分数据缺失与数值为零。
Pilot 判断分别列出离线门禁通过/失败/跳过和真实服务已验证/未验证/失败；P1 缺口不能自动标为通过。
真实服务未验证不阻塞 Pilot，但须披露风险；两级验收清单与执行阶段见 [pilot-validation.md](pilot-validation.md)。
阶段转换仍遵守 [入口边界](../SKILL.md#入口与执行边界)，不因离线通过自动启动 pilot 或 production。

配置解析测试显式从空环境启动以验证 JSON/env 优先级，会有意覆盖 autouse fixture 的 SF_SEARCH_PROVIDER；每例自行建立所需 JSON/假密钥并恢复全局配置。
coverage JSON/TXT 已含 missing_lines/missing_branches；缺口须按 scripts/、assets/ 汇总，并单列 CLI 入口与子进程统计边界。使用只读工具（不导入被测代码）：

```sh
<python> <skill>/tests/coverage_inventory.py <coverage.json> \
  --skill-root <measured-skill> --coverage-root <original-measured-skill> \
  --manifest <frozen-skill.json> --process-scope parent_only \
  --output <new-inventory-directory>
```

从原 coverage 命令的工作目录执行，coverage-root 用绝对路径；manifest 为测量时相对路径→SHA256 映射。工具验证报告对应源码与总数，拒绝基线不匹配和覆盖已有输出目录。
目录分类互斥，CLI 是正交维度：静态 main()/__main__ 入口，不与 scripts/assets 相加；其下调用的普通函数仍归 other。
子进程调用点清单只表示静态引用，既不证明实际运行，也不证明被 coverage 采集；默认 parent_only，只有已配置并核实子进程覆盖收集时才能使用 subprocess_included。
父进程未命中须区分 CLI/隔离执行器的统计盲区与其他待调查缺口；其他缺口也不自动等于测试缺陷或不可达。
报告可复用原覆盖率产物作分类分析，但须写原测量版本、源码哈希与命令，不冒充新一轮覆盖率。
不得为达覆盖率目标添加镜像断言。90/85 仍为改善目标，不阻塞 Pilot；测试不证明模型准确率。

## 环境异常与复跑

已观察到两类不同事件，不能合并归因为“沙箱 SIGSEGV”：最小 asyncio.to_thread 程序在受限
沙箱返回 42 后关闭挂起，同次对照在沙箱外正常退出；另一次沙箱外全量分片在附加超时堆栈
转储附近 SIGSEGV。后者根因未定位，前者的最小脚本不能声称复现或解释 SIGSEGV。
原始日志与失败尝试保留于项目验证产物；关闭附加转储后的分片复跑通过不证明崩溃原因已定位。

下次全量运行前，用相同解释器与权限运行线程关闭探针，输出须为新文件：

```sh
<python> <skill>/tests/asyncio_thread_probe.py --output <new-report.json>
```

探针不调用网络或模型，只观察子进程能否完成 asyncio 线程池关闭；失败时保留 stdout、stderr、
退出码或超时。探针通过也不保证完整套件不会 SIGSEGV。复跑须标明只重跑的分片与配置差异，
失败/超时/崩溃尝试不计作通过，也不因一次复跑通过声称故障已解决。
