# 证据协议

> 本文件唯一维护：证据资格、禁止推断补证、字段语义、部署边界前缀、案例归属与来源角色。跨职责规则通过链接引用其权威文档。

## 问题定义

每个候选案例必须先建立八字段问题定义：现实问题、参与方与角色、输入与输出、约束、既有方案、量子机制作用、成功条件、部署边界。production 写入 `case_problem_definitions` 表，每个字段一行；calibration 将八字段内嵌到对应案例的 `problem_definition` 对象，结构与表一致。字段级结论遵守同一引文协议；缺证时 `value_text` 为 NULL 并写 `reason`。只有八行全部有证据或显式缺失原因时 `problem_definition_complete = 1`，问题定义不完整的案例不得进入 Track 准入。

问题定义审计表模板：

| 字段 | 内容 | 原文短引与位置 |
|---|---|---|
| real_world_problem | 场景中谁面对什么问题。产业部署、研究部署、公共部门应用均可，须有具体系统、具体参与者和具体任务。仅研究动机、装置描述或理论框架不满足。 | source_id；版本/节/页/段 |
| parties_and_roles | 具体系统中的参与方及其任务角色，不把作者或合作者名单直接当作参与方。 | …… |
| inputs_and_outputs | 具体系统任务的输入与输出，不把孤立实验参数或测量结果直接当作任务输入输出。 | …… |
| constraints | 具体系统任务所受的物理、操作和安全约束，不使用泛化描述。 | …… |
| existing_practice | 该场景当前使用的既有方案或技术，可以是产业部署、研究原型或已有系统。须指向具体实现，而非泛化相关工作；不等同于 Track 的经典替代方案判定。 | …… |
| quantum_mechanism_role | 量子机制在该场景中解决什么问题、替代什么方案或提供什么能力。须指向具体机制，而非泛化量子优势或仅列研究贡献。 | …… |
| success_criteria | 具体系统任务的成功条件，不把无任务联系的测量结果当作成功条件。 | …… |
| deployment_boundary | 该场景的部署边界，必须以 `experimental: ` / `pilot: ` / `production: ` 前缀开头。研究部署可标 experimental: 或 pilot:，须有正文支持，不推断部署阶段。 | …… |

关键字段为 `real_world_problem`、`parties_and_roles`、`constraints`、`quantum_mechanism_role`。
缺证且无显式 reason 时为 `problem_definition_incomplete`，不得进入 Track；具体系统、参与者
和任务均未建立时才为 `not_a_real_world_problem`，研究部署本身不构成拒绝理由。
只有证据或原始 `record-gap` 的非空 reason 能计入审计完整度；单篇缺失观察不得自动补成案例 reason。
缺失字段必须写明缺失原因；不能用空白或推断代替。`case_problem_definitions.evidence_level` 只允许 `primary` 或 `secondary`，问题定义字段不得使用 `ai_inference`，因为问题定义直接决定案例是否进入 Track。

## 禁止推断补证

只引用本次实际打开的正文；元数据只作线索。禁止用训练记忆或 `ai_inference`
补问题定义、准入、评分及非空定量值。缺证保留 `insufficient_evidence` / NULL，
按适用字段显式记录缺失原因；失败归档。定量值只允许有证据的确定性换算。
单一独立来源标记 `single_source=1`、置信度最高 medium；C3、S2 优先要求两个独立来源。
Bell 关联不得描述为超光速通信；领域排除以 `config/exclusions.yaml` 为准。

`cases.deployment_stage` 只复制部署边界前缀对应枚举；没有正文支持不推断阶段。

## 文档与独立性

搜索结果摘要不是已打开的原文。先成功打开全文、专利或报告，再记录 source_id、URL、文档版本、opened_at、run_id、batch_id；有本地原件时记录 SHA256。无法访问正文时记 open_failed，不补证。种子 arXiv ID 只是待查线索，不预设其标题、结论或真实性。

### 来源角色

`case_sources.role` 表示来源相对于单个案例的证据角色，按案例分别判定：

- `primary`：该来源至少支持八个问题定义字段中的 4 个，或支持该案例某个 Track 的至少 2 项准入条件；
- `supporting`：该来源对案例有证据贡献，但未达到上述阈值。

同一来源对同一案例只能有一个角色，对不同案例可以分别判定。`sources[].evidence` 是来源级证据摘要，问题定义字段和准入证据是独立的证据路径；不能用摘要数组是否为空推断 `primary` 或 `supporting`。渲染器必须依据字段/准入引用密度判定角色。

DOI、arXiv、规范化 URL 记录别名，版本号单独保留；同一文档的镜像、预印本和发表版本不能算独立来源。两个独立来源须提供各自证据及独立性说明，不能把相互转述当交叉验证。旧缓存只可跳过分析，不算本次已打开；需要重新评估时显式发起重新打开/更新，不静默绕开缓存。

## 记录格式

每条有结论的证据对象必须包含：

```json
{"source_id":"规范化标识","search_log_id":123,"quote":"原文短引","location":"版本 + 页/节/段/表/图","unit":"ns","evidence_level":"primary","confidence":"medium","_source":"from_document"}
```

`case_evaluations.evidence_level` 在准入为 `insufficient_evidence` 或评分为 NULL 时可为 NULL；其余有证据的评估必须为 `primary` 或 `secondary`。`unit` 对每个定量字段必填；准入和评分不要求单位。`_source` 仅用于 `case_evaluations`；`case_problem_definitions` 不需要 `_source`，其证据层级只允许 `primary` 或 `secondary`。多来源存于 `evidence_json` 数组，数组元素统一为 `{source_id, search_log_id, quote, location, evidence_level, confidence}`；顶层列保存数组第一条。quote 必须逐字对应实际原文，不把翻译当原文；理由可中文。每条短引 ≤50 字并遵守来源整体引用额度，不为满足模板重复大量引用。

缺证时保留准入 `insufficient_evidence` 或评分 NULL，reason 说明缺什么；quote/location 可 NULL，不能伪造“未提及”的引用。已证实为 false 的准入也需证据。C3、S2 缺少第二独立来源时 `single_source=1`，confidence 不得 high。

在线 Candidate 的 confidence 仅允许 low / medium；high 是契约违规。两档均可进入双审，
该标签不构成 filled 的拦截门槛；填充仍须接地、有效绑定、双审、来源资格及无冲突等条件全部成立。
置信度供审计筛选参考，不表示经过校准的概率或已实现自动分层抽样。

## 定量与字段来源

`metrics_provenance` 的每个键对应 cases 的非空定量字段，值包含上述全部元数据、原始值/单位、规范值/单位和确定性换算说明。ns、USD、km、年为标准单位；纯计数用 count，无量纲比率用 ratio，布尔量用 boolean。仅允许确定性单位换算，不自行估算成本、部署时间、资源数或优势比；非美元成本若无有证据的汇率，美元字段 NULL。

范围写 min/max；只有 max 列的指标仅在原文明确给上限或明确单值时使用，不把任意范围端点冒充独立测量。单值可写到现有单列或 min=max，不添加不兼容的 _point 列。“约 10 微秒”保留明确点值及近似标记，不发明误差区间。“微秒级”若原文没有界定上下限，不自动写 1–1000 微秒，数值留 NULL，原始量级保存在审计记录；只有来源给出量级边界时才换算区间并标 low。

所有关键非定量字段的来源放 `field_provenance`，每个对象都有 `_source: from_document` 和证据；`scenario_description_source` 可为 ai_inference。元数据如 case_id、phase、状态、计算总分由流程生成，不冒充文档内容。总分是已证据评分的确定性聚合，不是新的文献测量。

写库前逐字段验证：已打开且同 run 的日志外键、引用与位置、来源层级、单位、来源标记、范围顺序、布尔值、两来源规则。非空定量 quote 覆盖率必须 100% 才可提交；80% 是批次诊断告警线，不是允许缺证入库的门槛。DDL 只提供结构检查，不能代替这些语义验证。


## 来源打开层级

`opened`、`opened_metadata_only` 及其事件字段、计数和证据禁用规则以 [batch-schema.md](batch-schema.md) 为唯一权威。本文件只要求证据引用服从该状态：元数据级来源不得作为问题定义、准入、评分或非空定量字段的证据。


## 写入前的源接地验证门

每批证据候选先调用 `scripts/validate_grounding.py`，或显式调用 SearchOS access skill
`assets/quantum_grounding`，接口及示例见 integration.md。
验证本 run 的 opened 正文、source_id、文档版本、非空 quote/location，并检查引文
逐字或[受限提取格式归一](../assets/quantum_grounding/skill.md)后的存在性，记录原始提取文本 SHA256 和字符偏移；不做 NFKC 或数字/大小写/否定词改写。
OCR 错字、数字/否定词变化、近似句子不自动放行。模糊搜索可辅助定位后修正引文。

此门只验证字符串；页/节位置和语义支持仍需独立复核，特别检查否定、条件、威胁模型、
实验/部署边界，以及是否把组件安全外推到端到端任务。确认支持之前不写为可用证据。
失败候选以 grounding_failures 保存；找不到原文为 quote_not_found，语义不支持为
semantic_mismatch。保留缺证/null，不静默丢弃审计、不把失败视为准入 false 的证据。

该 access skill 返回 facts=[]，不会自动给 SearchOS Evidence Graph 入图；它不是
全局中间件。当前原生工作流由 Agent 显式调用、持久化审计并执行后续语义复核。
production 仍须通过原有字段/单位/两来源检查，字符串门不替代任何领域准则。


## 案例归属与独立语义复核

引用存在仅通过字符串门。在线归属判断必须读取引文所在正文上下文，并识别目标案例的具体系统/协议。
根论文可包含不归属于该案例的背景；引用论文也不能因相似机制、同作者或引用关系就继承案例归属。
正文有明确身份或直接联系才 attributed；有歧义或需要推断则 abstained；仅一般概念或另一系统则 absent。
研究部署只要明确具体系统、参与者和任务即可作为现实场景；泛化动机仍不满足。
case_description 应明确案例身份，不能只提供无定义的内部编号。上下文不足时保留不确定，不靠文献深度猜测。

归属通过后，用独立请求核查语义支持、位置及该字段规则，特别检查否定、条件、威胁模型和组件/整体边界。
代码执行边界统一见 [判断层级表](../SKILL.md#约束执行层级)。
模型拆分不是正确性保证；两次调用可以同模型，但错误可能相关。契约、导入和缓存见 integration.md。
