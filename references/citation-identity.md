# 四服务引用身份核验

本文件维护服务选择、回执、分歧与代码复用边界。核验只建立标识/标题的元数据一致性，
不证明正文支持、真实性、量子优势或证据穷尽。发现搜索继续统一用 SearchOS，
arXiv 的身份 ID 查询不是已移除的关键词搜索后端。

## 配置与兼容

默认不请求引用服务，identity=unknown/reason=backend_disabled，报告注明“未启用”，不产生失败警告。
新配置显式给出允许调用的服务，顺序不决定主服务：

```json
{
  "citation_identity": {"enabled": ["crossref", "arxiv", "openalex"]},
  "citation_expansion_backend": "openalex",
  "max_citation_requests": 20
}
```

以上示例适用于仅已配置 OPENALEX_API_KEY、暂不使用 S2 的情况；需要 S2 时可显式添加 semantic_scholar，无须先取得 key。
密钥放项目 `.env` 并通过 `--env-file` 加载，或放进程环境；不写入在线 JSON。
Crossref/arXiv 不要求 API key；S2 的 key 可选，本适配器使用 OpenAlex 时要求 OPENALEX_API_KEY。
S2 [官方教程](https://www.semanticscholar.org/product/api/tutorial)说明论文详情查询的 key 可选但推荐；匿名用户共享限流额度，可能立即收到 429。匿名失败不表示必须有 key，也不表示论文不存在。收到 429 仍按下文暂停该服务，不持续重试刷成功。
启用配置和填写 key 是两个步骤，填写 key 不会自行启用服务或发送请求。
以上字段并入在线配置，其余 cases/查询/运行预算仍必需。enabled 默认空，不能重复或含未知名称。
能力接入不等于启用。只调用 allowlist 中的服务；未启用的主服务不会被偷偷调用。
旧 citation_backend=none/openalex/semantic_scholar 继续支持，也接受 crossref/arxiv；
内部等价于单服务 allowlist，既有 S2/OpenAlex 引用扩展保持兼容。
新 citation_identity 与非 none 的旧 citation_backend 同时出现时报错，不猜测迁移；
旧 workspace 保持原配置及归档执行基线，不迁移历史状态。
新配置引用扩展默认关闭，需单独选择 semantic_scholar/openalex；不能选择 Crossref/arXiv 做扩展。

| 标识 | 主服务（须已启用） | 按需补充（须已启用） |
|---|---|---|
| DOI | Crossref | S2，仍未 verified 才查 OpenAlex |
| arXiv ID | arXiv | S2 |
| 两者 | 两个主服务分别查；不凭标题合并预印本与正式版 | 按各自标识补充 |
| 无标识 | 不发请求，unknown/no_identifier | 不做标题搜索 |

主服务有 unknown/mismatch 或没有已启用且适用的主服务时才调用补充服务。
所有适用的主服务先查完；任一 mismatch 永不被补充服务的 verified 覆盖。
仅 expected-title 没有 DOI/arXiv ID 不能 verified；无 expected-title 时保留已取得元数据但为 unknown。
已返回的多个标题仍互相比对，发现分歧会拦截。

## 三态、分歧与版本

- verified：该标识端点与 expected-title 的规范化编辑相似度 >=0.70；保留实际返回标识，显式不一致为 mismatch。
- mismatch：标识、指定版本或标题不一致；多服务标题相似度 <0.70 也形成冲突。
  总状态 mismatch，cross_check=cross_check_conflict，阻止相关来源候选入图；source_depth=unverified，
  grounding_failures 保留 citation_mismatch。不是造假判定，不删除正文、候选、接地或双审记录。
- unknown：缺标识/缺标题、不适用、未收录、超时、限流、无效/缺标识响应、回显密钥导致的响应脱敏、版本无法核验或请求预算不足。
  不降低正文证据资格。显式启用后导出 citation_unverified；关闭时不产生该警告。

两个及以上服务均 verified 才标 cross_check_verified；有 verified、其余 unknown，或仅单服务 verified，
标 cross_check_partial。任何 mismatch 或标题冲突优先于 verified。全部 unknown 为 citation_unverified。
未调用的服务不伪造 unknown 回执；enabled_backends 和 checks 清楚区分启用范围与实际核验范围。
标题规范化只用于书目匹配，不能用于正文 grounding；0.70 是启发式阈值，不是语义/身份准确率保证。

Crossref 是注册机构之一，只覆盖其收到的元数据；404=unknown/not_covered_by_crossref，
不等于 DOI/论文不存在，不能据此判 mismatch。当前未接入 DataCite/CNKI 等注册机构。
arXiv ID 查询保留 v1/v2；请求明确版本却收到不同版本为 mismatch，聚合服务不提供版本为 unknown/version_unverified。
正文版本与哈希继续独立绑定，不因标题相同或元数据引用关系合并正文。
发现队列既有基础论文 alias 去重不变，已明确指定的正文 URL/版本不被替换；身份请求缓存按完整版本区分。
人工确认冲突后，应在新 workspace 使用经核实的标识/标题重新执行；本版没有自动解除或改写历史冲突的入口。

## 回执、预算与失败

online.citation_requests 是 adapter 事实的一部分，持久保存每个唯一端点/非密钥参数的请求：
backend、endpoint、request_url（移除密钥）、at、duration_seconds、status/status_code、Retry-After、
response_sha256、response_body（按编码保存正文；仅回显密钥被删改并标记）、budget_consumed。
单次元数据响应最多 2,000,000 字节（解压后）；流式读取，超出为 unknown/response_too_large，不重试。
完整响应的 response_hash_scope=complete_response；超限仅留上限内的原始前缀，
response_truncated=true、response_hash_scope=received_prefix，哈希仅对应前缀，不冒充完整回执。
此上限适用于有界身份/一跳扩展响应，不能作大规模批量导出接口使用。
checks 保存每服务的 state/reason、请求及返回标识、原始/规范化标题、版本和相似度。
不保存鉴权头或密钥查询参数；异常只保存类型和分类，不保存可能携带密钥的异常文本。

每个 HTTP 请求先持久保留 started 和预算占用，之后才发送；身份与引用扩展共用 max_citation_requests，
剩余运行时间同样约束等待及 IO。预算不足返回 unknown，不破坏已经打开的正文。
同 workspace、后端、完整标识/端点参数的成功或失败均复用；标题变化重新计算分数，不重复请求。
中断留下的 started 不重发，恢复显示 process_interrupted。连接/读取/超时类传输异常最多重试一次，
首次失败与第二次请求分别持久占用预算，保存 attempt/retry_of；至少等待 1 秒并继续遵守服务节流。
第二次结果也缓存，进程恢复不会产生第三次请求；HTTP 状态错误、无效响应、身份冲突不重试。
HTTP200但身份结构/扩展结果容器无效时，请求回执为failed/invalid_response；原响应保留，失败缓存命中不重新占预算。
缺少结果容器不解释为零条结果；明确的空列表才可记为空结果。
429 后在该 workspace 暂停该服务后续新端点，保留 Retry-After；不会以切换 IP/浏览器绕过。
同服务串行节流，arXiv 请求至少间隔 3.1 秒，其他服务至少 1 秒，恢复也读取持久时间锚点。
宿主上其他进程/项目的全局服务配额不由 workspace 锁保证，操作者仍须协调总访问速率。

引用扩展只用 S2/OpenAlex；已 FILLED 且无冲突的 depth=0 根节点，每父节点最多 5 个新任务、depth=1。
复用既有 adapter 的 DOI/arXiv/URL 去重与 Frontier 上限；元数据只作发现线索。
无标识节点 skipped；端点失败 failed，部分方向成功 partial，不把失败解释为空结果。

## 参考与直接复用评估

固定参考 academic-research-skills 提交 a3ef8c79d888b90aaaaecce7f42fbc3fd082d5ab，
其中 semantic_scholar_client.py、openalex_client.py、crossref_client.py、arxiv_client.py 为四服务客户端。
其仓库 LICENSE 为 CC BY-NC 4.0（Cheng-I Wu，2026），不是 MIT/Apache；
本次不复制、导入或 vendor 这些客户端，避免给本 skill 引入非商业用途限制。

此外客户端内部同步 sleep/重试、标题搜索回退与返回 None 的部分路径不符合本地
“逐请求预算/原始回执/不凭未收录判不存在/版本绑定/不重试 HTTP 错误”契约；
S2 客户端还依赖上游 contamination_signals 等模块。未发现必须依靠上游运行时才能调用的 API。
因此采用四索引原则与标题交叉检查思想，复用现有 httpx/标准 XML 解析基础设施，
按官方协议独立实现本地适配层；领域审计和状态所有权继续由 adapter 维护。
后续上游若提供兼容许可和可注入的传输/预算/回执钩子，再评估直接复用；不是默认永久排除。

之前本地仅有 S2/OpenAlex；Crossref/arXiv 身份核验是未落地部分，并非搜索统一时误删。
v14 补齐两服务；未恢复 arXiv 关键词搜索，也不引入上游多 agent/四索引污染判定运行时。
四条复用准则应用于承担对应职责的组件；满足准则只是可复用资格，不意味着自动扩大 SearchOS 基础设施范围或引入其运行时。纯 HTTP 客户端不必理解量子 Track，
但适配后的完整执行链必须满足状态所有权、审计绑定、停止和领域规则。

官方 API 依据：[Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)、
[arXiv 用户手册](https://info.arxiv.org/help/api/user-manual.html)、
[arXiv 使用条款](https://info.arxiv.org/help/api/tou.html)、
[S2](https://api.semanticscholar.org/api-docs/)、
[OpenAlex 鉴权](https://help.openalex.org/api/authentication/)。
