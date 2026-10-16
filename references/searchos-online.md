# SearchOS 在线补证入口

> 本文件唯一维护：在线 CLI、模型配置、预算、分段、有限恢复与调用观察。跨职责规则通过链接引用其权威文档。

`scripts/searchos_online.py` 为已有候选自动执行 SOCM 缺口任务：搜索、读取正文、
类型化抽取、字符串验证、独立模型复核、证据入图。它使用 SearchOS 模型工厂、
provider 契约、Frontier 和隔离 access executor；调度桥位于 skill 中。
不启动原版 SearchSession，不与原版 Orchestrator 同时写同一 workspace。
使用 ContextGem 抽取、claim ledger、独立归属 judge 和语义 judge；支持一跳引用扩展与 batch 导出，不自主新增案例。

## 配置和调用

目录由 `scripts/searchos_project.py` 集中管理，默认项目根为当前工作目录，可用
--project-root 指定。`searchos_project.py init --case-id ... --description ... --query ...`
直接生成 artifacts/quantum-scout/config/online-pilot.json 和 env.example，已有配置不覆盖；
`searchos_project.py runtime` 直接生成 artifacts/quantum-scout/runtime/manifest.json 和 requirements.lock。

复用 SearchOS 的 provider/model/role 配置模型与运行时解析。`searchos --setup` 已配置模型时，
模型卡、连接与角色绑定继续放在同一份 `web_settings.json`，真实密钥放 `.env`，无需重复填写模型环境变量。
例如百炼普通 API 的 `/root/SearchOS/.env`：

```dotenv
DASHSCOPE_API_KEY=填写本机密钥
```

只有尚未使用 JSON 配置时，才用 `SF_PROVIDER=dashscope`、`SF_MODEL`、`SF_FAST_MODEL`
提供环境基础模型；JSON 的显式模型/角色覆盖环境基础配置。密钥仍从环境变量读取。
Qwen Coding Plan 使用 `SF_PROVIDER=qwen-coding`，仍是 DASHSCOPE_API_KEY，但密钥属于
不同产品。DeepSeek 使用 `SF_PROVIDER=deepseek` 和 DEEPSEEK_API_KEY。
自定义地址用 SF_API_BASE。密钥不写入聊天或研究产物。

`--env-file` 显式加载 dotenv，已有环境变量优先。JSON 路径优先级为：
`--settings-file` > `SF_WEB_SETTINGS_PATH` > 所选 env 所在项目的 JSON > 当前 SearchOS 安装默认路径。
项目内识别 `web_settings.json` 或 `.venv/lib/python<当前版本>/site-packages/web_settings.json`；
两者同时存在则拒绝猜测，须显式选 `--settings-file`。这使独立虚拟环境也可复用 `searchos --setup` 的配置。
显式路径缺失、JSON 无效或核心角色绑定无效时退出 2，不静默退回其他模型。
未找到默认 JSON 时仍兼容原环境配置；仅在进程内应用，不自动迁移或写回配置文件。
doctor 与每次 invocation 记录配置路径、选择方式和 JSON SHA256，不记录密钥值。
角色为 orchestrator（新查询）、
extraction（抽取）、judge（独立复核）；也支持原有 SF_ROLES__/SF_PROFILES__ 覆盖。
复核使用独立请求和上下文，可使用同一模型，但不保证模型误差独立。

模型和搜索后端统一通过 SearchOS 共享配置解析：优先使用所选 JSON 的 `models.search_provider`，
未指定时由 SearchOS 根据 `SF_SEARCH_PROVIDER` / 已有 key 解析。用 SearchOS 设置入口选择 Serper 后，
本 skill 无需另选后端；工厂也复用 SearchOS 的 `build_search_provider`。候选、调用预算和停止仍由任务 JSON 管理。
新任务省略 `providers`，案例 `queries` 使用普通搜索字符串列表；读取时把实际后端与查询一起固定到本次配置快照。
如保留旧式 `providers` 或按后端组织的 queries，它们必须与共享选择一致；不一致在创建 workspace 前退出 2。
已移除专用 arXiv API 后端与分页选项 `pages_per_query`，不静默重写旧查询或恢复旧基线。
arXiv 论文仍可经 Web 搜索或已知 URL 打开；正文版本、来源去重与引用身份规则继续适用。
共享 JSON 中的重试和 token 设置不放大本入口边界：仍关闭 SDK 重试，每次模型输出最多 4096 token。

在线 JSON 配置示例，候选描述和种子只作检索线索，不预设准入结论：

```json
{
  "cases": {
    "TEL-0007": {
      "description": "检查弱相干脉冲时钟同步方案的问题定义及安全主张，不预设量子优势",
      "queries": ["2510.00199 quantum clock synchronization"]
    }
  },
  "max_rounds": 5,
  "max_model_calls": 64,
  "max_seconds": 1200,
  "call_timeout": 60,
  "max_sources_per_round": 2,
  "results_per_page": 3,
  "max_context_chars": 40000,
  "stall_rounds": 3,
  "citation_backend": "none",
  "analysis_limit": 20,
  "max_cases": 10,
  "batch_size": 5
}
```

v14 省略预算项时采用上例默认值：64 次模型调用、5 轮、1200 秒；不自动读取 scope.yaml 的 phase 上限。
预算根据单案例五表的理想下界调整：八字段及两条 Track 全部准入/评分单元共 27 个，
至少需要 5 次抽取 + 54 次双审 = 59 次模型调用。64 次只留有限余量，
多分段、ContextGem 内部多次抽取、纠错、失败或多案例仍可能提前耗尽，不保证覆盖完成。
单案例只要一条 Track 形成合法覆盖链即可完成覆盖；准入拒绝与显式不适用会改变实际成本。
既有 JSON 显式配置的 8 calls / 2 轮 / 300s 仍有效，可用于部分校准，不自动提高或重写。
引用身份默认关闭；这些上限只有执行 run/open-source 才可能消耗，doctor 不发请求。

max_model_calls/max_seconds/max_rounds 按每次 invocation；analysis_limit/max_cases、
来源与查询的重试配额、max_citation_requests 按 workspace 累计。时间为协作式截止：
等待和网络可取消，PDF 取消会清理子进程，HTML 只读解析线程可能稍后结束，不能承诺硬实时退出。
正文字符预算只计算所选 segment，不等于包含提示词/审计上下文的模型总 token 窗口。
全部限制、容量组合和调整依据见 [限制与预算](limits.md)。

phase 仅作离线/批次规划，不自动用于在线，也不自动追加调用或恢复循环。
验证同一 workspace 最多恢复一次，必须使用其原配置 JSON；仍因预算终止可接受，不追到完成。
报告分别显示本次 invocation 与 workspace 累计调用；同 workspace 恢复要求配置不变。
高预算/长文测试使用独立 JSON 和 workspace，不覆盖历史配置、事实或基线。
若做小预算探针，应显式填写 8 calls / 300s 等更低上限；若扩大长文范围，按实际缺口配置，
不默认把 max_context_chars 扩至 120k。新分段抽取仍消耗本次总预算。
先处理已发现未读来源/正文分段，再生成定向查询。
搜索使用 SearchOS 原接口，每查询一个有界结果集，不声称支持分页；Serper/Tavily 需对应密钥，Tavily 另需可选依赖。
SearchOS 的 RagFlow 仅适用于已配置内网端点和凭据的环境；外部环境应在共享设置中明确选择 Serper/Tavily。

```bash
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_online.py doctor \
  --config artifacts/quantum-scout/config/online-pilot.json --env-file /root/SearchOS/.env

uv run python /root/.codex/skills/quantum-scout/scripts/searchos_online.py run \
  --config artifacts/quantum-scout/config/online-pilot.json --env-file /root/SearchOS/.env \
  --workspace artifacts/quantum-scout/workspaces/online-pilot-01
```

已知论文正文直接走同一 runner，不经搜索提供商；仍执行抽取、双复核、预算、checkpoint 和导出：

```bash
uv run python /root/.codex/skills/quantum-scout/scripts/searchos_online.py open-source \
  --workspace artifacts/quantum-scout/workspaces/online-pilot-01 \
  --url https://arxiv.org/pdf/2510.00199 --case-id TEL-0007 \
  --config artifacts/quantum-scout/config/online-pilot.json --env-file /root/SearchOS/.env
```

case-id 必须属于配置和 workspace；本次只调度该案例，URL 不预设归属成立。
`open-source --expected-title "论文标题"` 仅为该 URL 提供比对标题，优先于检索元数据；不自动查标题。
不新增 fetch-expected-title 或后台标题请求。缓存正文的标题校验不重复；若要更换已缓存的比对标题，
显式新建 workspace。verified/mismatch/unknown 的含义见审计层。
正文进入 online.sources，随后 `run` 优先复用缓存再发新查询；配置须一致。临时 runner 不再是执行入口。

doctor 不联网，只检查角色构造、密钥是否存在和依赖；ready 不代表端点已实测。
省略 --config 时读取 artifacts/quantum-scout/config/online-pilot.json；doctor 直接写
artifacts/quantum-scout/validation/doctor.json。run 省略 --workspace 时在 artifacts/quantum-scout/workspaces/online-<UTC时间>/
新建会话，并直接更新 artifacts/quantum-scout/validation/online.json；显式 --workspace 用于恢复。
缺配置时 run 在创建研究 workspace 前退出 2。run 会产生真实模型调用；退出 0 只表示
执行器保存了有解释的终止状态，不能视为研究完成。

## 来源和证据回流

搜索摘要只作线索，arXiv abstract URL 转为 PDF 后下载正文。保存 PDF/HTML 原件、
正文文本和 SHA256。PDF 使用 pdftotext，以 page:N 定位；HTML 使用保存的提取段落
paragraph:N 定位，不冒充出版物页码。正文按上下文预算分段，未处理部分保留待办；
单段过大则报错。同 workspace/run 可复用已打开正文，不把旧 pilot 引文当作本次证据。

每条候选只允许目标字段、领域枚举、primary/secondary、low/medium、≤50 字符原文短引。
先调用真实隔离字符串门，再确认引文位于声明的段落/页，然后执行独立归属复核和语义复核。
仅 attributed + supported + location_checked=true + domain_rule_met=met 才入图；其余判断均审计并保留 uncertain。一个来源的 missing 观察不自动完成整个案例问题定义审计。
准入依赖和冲突处理仍由 adapter 执行，评分不能越过准入。
模型输出违反类型契约或反证短引无法映射到所声明正文分段时，保留原始输出和具体错误，
共用最多一次格式纠错机会；反证短引按字符计数，必须为连续原文，不允许省略拼接。纠错消耗同一
调用预算，不修改领域枚举、置信度限制或引文规则。再次不合规则报错保存恢复点。

`state/quantum_adapter.json` 的 online 对象 保存查询及结果集、来源请求、模型输入/输出、失败、分段进度
及每次 invocation；`reports/online.json` 是最近一次摘要。失败同时投影进 Failure Memory。
搜索传输失败的显式恢复见文末；引用传输失败最多一次预算内重试，详见引用身份契约。旧审计保留。
URL 缓存只用于 run 内避免重复读取，不将镜像计作独立交叉验证来源。

在线执行使用独占锁；异常释放任务。进程被杀后再次 run 会把前次 running invocation
标为 process_interrupted，并释放它拥有的任务，不释放人工领取任务。grounding 和
复核记录保留。不要与其他 adapter 写入命令并行操作同一 workspace。

## 终止语义

状态和完成标志由 [停止契约](batch-schema.md#停止契约当前版本) 定义。
在线报告与校准批次分别保存；批次经渲染器验证后写入
`calibration/batch.json`、`comparison.md` 和增量 `checkpoint-NNNN.json`。
每成功打开 batch_size 个正文来源保存普通恢复点，终止再保存 final checkpoint。
手动重新导出：`python skill/scripts/export_batch.py <workspace>`。

终止定义统一见 [批次停止契约](batch-schema.md#停止契约当前版本)。`operational_cause` 记录具体原因，
`claims_global_exhaustion=false`。人工抽查是可选事后质量标注，不阻塞覆盖停止；总预算保持不变。

## 抽取降级与引用扩展

默认 ContextGem 生成结构化字段、句子引用及 justification；本地确定性句子分割不下载模型。
每次 ContextGem 请求都经过统一调用计数与超时，关闭内部重试/并发。抽取服务或其输出格式
故障可回退一次原生结构化 LLM 请求，失败原因和降级事件均保存；回退无额外格式纠错。
预算耗尽、中断、句子引用映射失败、字符串门或语义复核失败不触发降级。
两条路径共享 Candidate 契约和完整证据门，不降低证据标准。ContextGem 句子映射逐候选验证；错引候选拒绝并审计，不拖累其他有效候选，也不触发回退或在其他句子中代找引用。共用[接地白名单](../assets/quantum_grounding/skill.md)，原始引文保持不变；不用 NFKC 自动放行。

judge 收到 `claim_ledger`：具体 claim、原文 span_excerpt、字符偏移、source_sha256、
已复核的不同值及当前正文分段。反证搜索与判定记录服从 [审计层](audit-layer.md#反证与决策链)。

引用身份采用默认关闭的显式多服务配置；Crossref/arXiv 主核验，S2/OpenAlex 按需补充。
配置、旧单后端兼容、三态/分歧、版本、共享 HTTP 预算及许可证评估统一见
[四服务身份契约](citation-identity.md)。身份与引用扩展服务分开选择，引用扩展新配置默认关闭。
既有 FILLED 根节点、depth=1、每父节点最多 5 个新任务和元数据不入图规则保持。

正文连接/读取超时等传输失败不会在本轮内自动重试；下一次显式 `run` 恢复允许再试一次，同一 workspace 同一 URL 总共最多两次。重试保留原发现时间及失败事件，新增 `source_retry` 审计；HTTP 状态错误、正文格式或证据错误不使用此路径。可重试正文计入待处理来源，防止误判操作耗尽。

ContextGem 输出中重复的段落 ID 在桥接层做无损集合合并（仅合并其原有句子 ID），以符合库的唯一性约束。原始模型响应和合并后的响应分别审计；不修改 value、quote、段落 ID 或补造句子 ID，之后仍执行引用映射、字符串门和独立复核。


## 两阶段复核与恢复

字符串门后调用 AttributionResult（独立归属上下文）；只对 attributed 调用 Judgments（候选、ledger、字段规则和正文）。
两次均用 get_model_for('judge')，模型调用预算分别计数；成功候选通常消耗一次抽取加两次复核。
归属输入的 source_depth 来自来源事实，Candidate 不接受该字段。两步的结果分别按 report_id/candidate_index 保存，
包括负面归属和语义 abstain。归属已缓存但语义缺失时只调用语义；两步都已缓存不重复调用。
模型原始响应记录在 online.events，决策记录在 attributions/reviews，判定失败保持 UNCERTAIN。

同一来源跨表不共享游标或抽取缓存。预算按各表的分段抽取次数加候选双复核次数估算；
8 calls 不保证完成单表，48 calls / 3 轮也不保证到达评分，准入未全 true 不调度评分。
抽取缓存绑定来源、正文版本、任务和正文分段，并保存当时覆盖的目标字段。
恢复时若当前缺口是这些字段的子集，复用原候选，只处理尚缺字段；目标扩展时重新抽取。
预算有限时先复核 real_world_problem、parties_and_roles、constraints、quantum_mechanism_role，再处理其他字段。
当前缺口缩小时，按 case_id/table_id/source_id/document_version 查最近 assessment，再校验字段名子集与分段总数。
子集继承数字或 done，记新 assessment_started 的 inherited_from；扩展从 0 开始，记 restart_reason=target_expanded，旧记录保留。
换案例/表/来源/版本或分段数变化不继承；旧事件缺少范围元数据时安全重启，不补造历史信息，仍可命中原抽取缓存。
current_assessments 按 case_id/table_id/source_id 选当前记录，pending 与导出共用相同范围语义。
处理前写入 assessments 的待处理游标；异常保留该批起点，成功才推进，只有全文结束才标 done。
候选复核逐条持久化，恢复复用抽取缓存并补缺失复核，不跳过同批剩余候选或后续页。

### 可选真实归属回归

`tests/live_attribution_regression.py` 可将指定历史候选作为**未验证输入**，重新真实搜索、下载相同正文，
检查正文 SHA256 后，经过正式字符串门、归属和语义流水线。它仅替换抽取环节，不注入 judge 结论，
因此不能算 ContextGem 端到端质量测试。需要 `--historical-workspace`、`--report-id`、`--config`、
`--workspace`、`--env-file`；调用消耗真实 API 额度。相同输入可恢复，工作区禁止混入其他回归输入。

反证、自检、引用三态、成本分类和当前布局规则见 [审计层与产物布局](audit-layer.md)。

## 执行观察

- source_opened.details.opened_order 记录 workspace 内去重正文的首次打开序号；缓存复用不新增，恢复不重置。结合发现轨迹核对来源顺序，不能据此声称 layer 优先级已强制。
- stop_decision 记录每次判断、继续/拒绝原因和终止证据；final=true 是最终退出记录。
- round_completed / round_interrupted 含轮次、task_id、calls_this_round（增量）、calls_cumulative（本次累计）；中断还含原因、pending_stage 与 pending_kind；含义统一见 [审计层](audit-layer.md#预算与派生诊断)。
- assessment_started 将游标键关联到来源和任务；source_context 记录实际提供的分段范围。导出 source_level 警告区分已提供分段与已完成复核，不按游标键数冒充来源数；type=unprocessed_chunks 表示已打开正文未处理完，unopened_sources 表示引用扩展来源未打开。
- 同一 runner/workspace 同后端连续两次 HTTP 429 记录 citation_backend_throttled，提示切换后端或稍后重试；计数仅在内存中，重启归零，不自动切换。

逐候选契约拒绝与错误细分类见审计层。真实验证按本次明确授权的次数执行；新的显式恢复授权可新增一次 invocation，
不把此前验证的“一次恢复”误读为永久禁止恢复。同 workspace 配置与 skill 基线仍必须一致，详见 [基线协议](audit-layer.md#受控变更与不可变基线)。
评分正路径必须在独立案例、独立配置/workspace 中由四项准入全部 true 且均有双复核证据后验证；
不得预填准入、混入另一论文历史或把“可能符合”当通过。评分已调度与评分达标分别报告，缺维度仍为 null。

comparison 按字段列出多原因及来源范围；轮次上限 round_limit 与调用上限 model_call_limit 分开显示。对 done 但有缺口的来源先只读诊断，不自动重抽或生成 record-gap。

固定 URL 模式只领取指定来源仍有可执行动作的任务；来源 assessment=done（含缺口子集继承）时跳过，失败来源遵守原有限恢复边界。无可领取任务时沿用 budget_exhausted / tasks_claimed_or_sources_pending，表示此执行范围没有可领取任务，不表示模型预算已用尽或全局来源耗尽。非固定 URL 调度不变。
归属 judge 接收引文段及本次抽取批次中前后各至多一段，带原位置标记；不额外打开正文、不越过批次范围，位置不存在时失败关闭。实际送达邻段不保证判定通过，也不要求模型在理由中复述页码。


## 搜索失败与显式恢复

每个 query_id 成功结果复用；失败在同次 invocation 不重试。仅 ConnectError、ConnectTimeout、ReadTimeout、
ReadError、RemoteProtocolError、TimeoutError、ProcessInterrupted 可在下一次显式 run 恢复时重试一次，
同 workspace 同 query 总计最多两次尝试。HTTP 状态错误（含 429）不重试，不按空结果/零新增处理。
先处理已发现正文积压；需要搜索时，先处理相关可重试查询，再生成新查询；存在可重试搜索时不能声明操作耗尽或收益递减。
记录 attempts/attempted_at/previous_attempts 与 search_retry 事件；原始失败事件、错误类型和 Retry-After 保留。
搜索重试也受原总预算约束，不触发后台或自动恢复。正文沿用独立的同类一次显式恢复策略。

状态与 API 复用边界见 [searchos-boundary.md](searchos-boundary.md)，doctor 无网络公布状态所有者和能力矩阵。
