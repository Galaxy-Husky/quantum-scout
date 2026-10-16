# SearchOS 领域适配与抽取/引用扩展

> 本文件唯一维护：离线适配器接口、绑定记录导入和恢复调用。跨职责规则通过链接引用其权威文档。

## 当前能力和边界

SearchOS 的 `SearchState`、`CoverageMap`、`Frontier`、`EvidenceGraph`、`StrategyMemory`
和 `WorkspaceManager` 提供派生调度视图。`quantum_adapter.json` 是在线 workspace 的
唯一权威事实源；`persist` 先验证事实投影再持久化，`repair` 从已提交事实重建 SOCM。
生产 SQLite 与在线研究工作区有不同用途，不存在两个并行写入的在线状态所有者。
修改任何 clone 仓库的代码前必须创建分支。参考源码放在 `/root`，本次不改上游代码。

| 组件 | 实际职责 |
|---|---|
| 领域配置 | 定义八字段、准入、评分、排除及证据协议，不调度运行时 |
| adapter | 审计事实、状态投影、任务领取、字符串门、独立复核导入、引用任务准入 |
| ContextGem | 正文抽取、句子 references、justification；所有内部请求计入预算 |
| claim ledger | 本地 DeepDive-inspired 结构，绑定 claim、原文 span、哈希和待检查反证；不运行 DeepDive 流水线 |
| 优先级启发式 | base + 0.2 × 目标缺口中 uncertain 比例，上限 1；非 ASReview 模型/主动学习 |
| 引用后端 | OpenAlex 或 Semantic Scholar 元数据；一跳、每个已 FILLED 父节点最多 5 个去重新任务 |
| 在线执行器 | ContextGem 优先，抽取服务故障时一次受控降级；独立 judge、预算、停止、恢复、checkpoint |
| exporter | 从复核事实导出 batch/checkpoint/comparison；复用渲染器守卫，无生产库写入 |

本文件描述本地领域配置、状态持久化和证据入口，本地命令不发起付费模型调用。
自动联网和模型调用使用独立的 [在线入口](searchos-online.md)，准备 workspace 不是完成研究 run。

## 环境与检查

独立验证门和旧 renderer 仅需标准库。schema_generator 另需 PyYAML；SOCM 适配器
使用项目 uv 管理的 Python 3.12 `.venv/`，安装 SearchOS 与 ContextGem。
在项目根目录执行 `uv sync --locked`、`uv run python skill/scripts/check_searchos.py`。
依赖约束维护于项目 requirements/，uv.lock 用于复现；运行源码修订记入 runtime manifest。
运行清单和依赖锁位于工作目录的 artifacts/quantum-scout/runtime/manifest.json / artifacts/quantum-scout/runtime/requirements.lock，
上游安装说明见 `/root/SearchOS/docs/installation.md`。不需要 Web 前端或浏览器扩展即可运行本地适配器。

```bash
uv run python /root/.codex/skills/quantum-scout/scripts/check_searchos.py
uv run python /root/.codex/skills/quantum-scout/scripts/check_project_environment.py
uv run python -m unittest discover -s /root/.codex/skills/quantum-scout/tests -v
```

检查覆盖 SearchSession 导入、真实 schema、四个领域 skill 的注册和隔离 executor，
不访问模型或搜索端点。当前执行沙箱内的 asyncio 子进程等待存在间歇超时：最小
print 子进程也能复现；同环境在沙箱外正常。受影响时应由宿主执行该检查或按环境
审批机制申请运行权限，不能把超时当无证据。SearchOS worker 自身仍使用禁网策略。
先前归因于 Conda 的判断不足；本次对照定位到了执行沙箱边界，不修改上游逻辑绕过它。

## Schema、技能与现有批次迁移

```bash
uv run python /root/.codex/skills/quantum-scout/scripts/schema_generator.py \
  /tmp/quantum-schema.json --case-id TEL-0001 --skills-dir /tmp/quantum-skills

uv run python /root/.codex/skills/quantum-scout/scripts/searchos_adapter.py prepare \
  artifacts/quantum-scout/workspaces/my-session --batch artifacts/quantum-scout/runs/<run_id>/calibration/batch.json
```

新案例可用 `--case-id TEL-0001` 代替 --batch；两者互斥。prepare 拒绝覆盖已有目录。
每个案例生成 27 个单元格：问题定义 8、Track A 准入 4/评分 5、Track B 准入 4/评分 6。
主键不作为证据列，避免自动 filled。历史值只作为 uncertain 候选；null/缺失原因
保持 missing；历史引用不自动复用为本次正文证据，不复制旧 completed 声明。

源码插件模板位于 skill 的 `assets/quantum_grounding/`；prepare 将它复制到 workspace 的 `skills/access/quantum_grounding/`，后者保留 SearchOS 注册器的 access 分类布局。

workspace 包含：

- `state/quantum_adapter.json`：本适配器的审计事实、配置快照、历史值、grounding 报告、独立复核和任务状态。
- `config/quantum_schema.json`：生成的字段/schema。
- `state/socm/search_state.json`、`state/socm/coverage_map.json`：使用 SearchOS 模型和写入接口生成的调度视图。
- `skills/strategy/`：quantum-nlc-admission、quantum-security-admission、quantum-scoring。
- `skills/access/quantum_grounding/`：字符串门副本；注册器可识别全部四个 skill。

本适配器专用 workspace 的 SearchOS 状态是审计事实的派生视图，不能同时让原版
SearchSession 独立改写同一目录，否则 repair 会覆盖那些未经导入的更改。在线
入口通过同一审计路径回写，不能只把路径传给 SearchSession 就声称完成接入。

## 调度与恢复

```bash
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_adapter.py summary artifacts/quantum-scout/workspaces/my-session
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_adapter.py next-task artifacts/quantum-scout/workspaces/my-session
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_adapter.py release-task artifacts/quantum-scout/workspaces/my-session <task_id> --reason '执行中断，现已恢复能力'
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_adapter.py add-case artifacts/quantum-scout/workspaces/my-session --case-id TEL-0002
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_adapter.py repair artifacts/quantum-scout/workspaces/my-session
```

next-task 持久化 running，避免重复领取；没有就绪任务只返回 task=null，不生成停止声明。
先问题定义，再准入，只有四项准入均经独立复核为 true 才调度评分；false 不由评分补偿。
八字段的显式缺失原因可完成审计，但不能算 filled。冲突使单元格恢复 uncertain，
同时保留 EvidenceGraph 的 conflict 边。新增案例扩大分母，不能删除困难案例提高覆盖率。
Frontier 超过上游 200 任务容量时显式报错，不让上游静默淘汰；应拆为明确案例范围。

record-gap 接受 JSON：table_id、case_id、field、status（missing/hard_cell）、reason。
hard_cell 还需非空 attempts 操作记录；不可达仍不计覆盖。已获独立复核支持的单元格
不能通过 record-gap 隐藏。缺口历史与失败模式保留在审计记录和 StrategyMemory 中。

写入由工作区锁串行化；先校验、原子写审计事实，再生成派生状态。中断后用 repair
从已提交审计事实重建，不重跑引用核查或重复复核。它不迁移 production SQLite。

## 字符串门与两次独立复核

原生字符串门仍可独立调用 `scripts/validate_grounding.py request.json report.json`；
退出 2 表示有失败，报告仍会写入。输入 source 包含 source_id/run_id/status=opened/
document_version/text，evidence 中每项含 case_id/field/source_id/quote/location。

适配器的 ground 另要求顶层 table_id、extractor_id、run_id=workspace 名；每个候选
包含 value_text、evidence_level（primary/secondary）、confidence（low/medium）。
此请求示例仅为接口说明，不是研究证据：

```json
{
  "run_id": "my-session", "extractor_id": "extractor-A", "table_id": "problem_definition",
  "source": {"source_id":"fixture","run_id":"my-session","status":"opened",
             "document_version":"test v1","text":"Two parties decide."},
  "evidence": [{"case_id":"TEL-0001","field":"parties_and_roles","source_id":"fixture",
                "value_text":"Two participants","quote":"Two parties","location":"test v1",
                "evidence_level":"primary","confidence":"medium"}]
}
```

```bash
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_adapter.py ground artifacts/quantum-scout/workspaces/my-session request.json
```

字符串通过仍为 uncertain，facts=[]，不入 EvidenceGraph。只接受逐字/受限提取格式归一匹配，
不更改数字、否定词或标点；记录原始提取文本的 SHA256 和字符偏移。调用方负责确认
输入是本次实际获取的正文，不能用模型重写文本冒充源。失败候选完整保留并进失败记忆。
同一请求按哈希去重。原生批次调用方仍须把失败数组追加到 batch.grounding_failures。

字符串门之后先判断案例归属，再单独判断语义和字段领域规则。两次请求均使用现有
`SF_ROLES__JUDGE`；不引入 fast model 配置面。独立请求与上下文不保证同模型误差独立，
拆分改善可观测性，不保证判定正确。共享守卫见 `scripts/review_policy.py`。

第一步 `attribute` 的三态语义由 [证据协议](evidence.md#案例归属与独立语义复核) 定义。
`source_depth` 由来源记录的 citation_depth 注入。
未确定归属保持 UNCERTAIN，不进入第二步。示例（不是研究证据）：

```json
{
  "report_id":"<ground返回值>", "candidate_index":0,
  "case_id":"TEL-0001", "location":"test v1", "value_text":"Two participants",
  "source_sha256":"<grounding.source_sha256>",
  "reviewer_kind":"agent", "reviewer_id":"attribution-judge",
  "attribution":"attributed", "attribution_reason":"正文明确识别该案例的具体协议"
}
```

`searchos_adapter.py attribute <workspace> attribution.json` 只导入已完成的判断，不调用模型。
第二步 `review` 沿用上述绑定字段，换用不同 reviewer_id，并提交 verdict、location_checked、
domain_rule_met、domain_rule_reason、reason 和结构化 counter_evidence_search。
反证对象只在 [审计层](audit-layer.md#反证与决策链) 定义，提交前按该契约组装。

`searchos_adapter.py review <workspace> review.json` 也只导入审计。语义 verdict 可以是
supported / semantic_mismatch / abstain，domain_rule_met 可以是 met / not_met / unclear。
`met` 表示候选值符合证据/字段规则，不等于准入值为 true；有充分证据的 false 也可 met。
只有 attributed + supported + location_checked=true + domain_rule_met=met 同时满足才入图。
其余结果包括模型自相矛盾的 supported+unclear 原样记录，不填充；abstain 不再只留事件。

每项判断绑定 case_id、value_text、location、source_sha256 和候选键。两名 reviewer_id
必须彼此不同且不同于 extractor_id；身份声明不能技术性证明评审者或模型误差独立。
禁止伪造复核记录让字段变绿。两阶段分别缓存到 attributions/reviews，预算中断后只补缺的
阶段，失败归属不消耗语义调用。新在线 ground 请求带 review_contract=4，避免误用旧缓存。

人工抽查使用 `audit-attribution <workspace> check.json`：沿用候选绑定字段，reviewer_kind
为 human，包含 reviewer_id、attribution_correct 布尔值和 reason。仅对双复核通过候选
抽查，每个候选一次。默认要求候选仍在当前覆盖链；`audit-attribution <workspace> check.json --post-hoc`
仅跳过此项，仍校验绑定、双复核、human、非空 reason，重复候选拒绝，不覆盖首条记录。
补录重算当前案例标签（含链外错误），不重跑搜索、不改写停止快照。此接口不篡改模型判断。
精确率为人工确认正确数 / 已抽查数，另报抽查覆盖率；未抽查为 unknown，不能视为 0% 或 100%。

## 外部框架的边界

ContextGem 使用 `/root/contextgem`，DocumentLLM 的传输钩子由本地桥接类包装，固定
当前已验证版本；升级后重新验证每次请求的预算和错误路径。references 必须映射回
本次正文 segment；justification 是抽取器意见，不是证据或独立判断。
仅抽取服务/返回格式故障可回退一次裸 LLM；字符串门、位置核对、judge 失败不触发回退。

DeepDive 仅参考 `/root/deepdive`（Socialpranker/deepdive）的 claim ledger/dissent 思路。
本地 `claim_ledger.py` 的字段是本项目契约，不声称兼容某个上游固定 schema。
counter_evidence 的范围和反证检索义务见 [审计层](audit-layer.md#反证与决策链)。

ASReview 仅参考 `/root/asreview` 的优先筛选思想；没有安装/训练其分类器。
启发式只改变 Frontier 优先级；公平轮转、前置依赖、准入与评分规则独立保留。

引用任务由 adapter 校验父节点的 FILLED 状态并回写审计事实。深度 1 来源不得再扩展；
DOI/arXiv 标识、来源 URL 和既有任务去重；无标识的节点记录 skipped。端点失败记录
failed，不当作空结果或自动重试。所有新来源必须重新打开正文、抽取、接地和复核。

停止契约见 [批次协议](batch-schema.md#停止契约当前版本)，版本演进见 [CHANGELOG](../CHANGELOG.md)。

核对来源：[ContextGem](https://github.com/shcherbak-ai/contextgem)、
[DeepDive](https://github.com/Socialpranker/deepdive)、
[ASReview](https://github.com/asreview/asreview)、
[SearchOS](https://github.com/antins-labs/SearchOS)。

结构化反证、引用身份三态和审计成本的新增契约见 [审计层](audit-layer.md)。
