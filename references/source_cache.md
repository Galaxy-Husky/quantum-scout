# 来源发现与本地缓存

> 本文件唯一维护：来源缓存身份及失效操作。跨职责规则通过链接引用其权威文档。

## 数量定义

每批分别记录：

- `discovery_limit`：搜索结果池大小，包含摘要命中、重复项和被排除项；从 `scope.yaml` 当前配置读取。
- `analysis_limit`：成功打开并读取正文的来源数上限；从 `scope.yaml` 当前配置读取（若当前 phase 提供 `phases.<phase>.analysis_limit` 覆盖则使用覆盖值）。
- `accepted_limit`：阶段允许纳入的唯一案例数，由 `phases.<phase>.max_cases` 或 `target_cases` 给出。

报告必须同时显示 `discovery_limit`、`analysis_limit` 和 `accepted_limit`；不能把搜索结果数当成已打开来源数。

## 缓存目录

在线发现去重仅规范化已识别身份：doi.org/dx.doi.org 的 DOI 大小写与编码、
arxiv.org/www.arxiv.org/export.arxiv.org 的 abs/pdf/html 路径、版本后缀、大小写及重复/末尾斜线。
发现身份忽略 arXiv 版本；显式 open-source 打开的不同正文 URL 仍保留实际来源 ID 与版本，导出不互相覆盖。
未识别镜像（包括未加入允许列表的镜像主机）、额外路径和不同 DOI 保留独立身份；不凭相似标题合并预印本/正式版。

启用 `cache_sources: true` 时，在工作目录使用：

```text
sources/<safe-source-id>/
  original.<ext>       # 仅在成功下载且允许保存时
  metadata.json
```

`safe-source-id` 只用于文件路径；数据库和日志仍使用规范化 `source_id`。`metadata.json` 至少包含：

```json
{
  "source_id": "doi:...",
  "canonical_url": "https://...",
  "document_version": "version of record or arXiv version",
  "retrieved_at": "UTC ISO-8601",
  "content_type": "application/pdf",
  "local_path": "sources/.../original.pdf",
  "sha256": "...",
  "status": "downloaded|open_only|download_failed|paywalled|not_permitted",
  "search_log_ids": [123]
}
```

哈希对保存的原始字节计算；仅 `downloaded` 状态要求非空 SHA256，`open_only`、`download_failed`、`paywalled` 和 `not_permitted` 状态的 `sha256` 可以为 `null`。`aliases_json` 应包含 canonical URL、URL 重定向、DOI、arXiv 版本和网页版本别名；内容哈希改变时视为新文档版本。HTML 页面可以缓存为 `.html`，但不能声称它是 PDF 全文。下载失败、付费墙或许可不明时只写 `open_only`、`download_failed` 或 `not_permitted`，保留 URL、错误和实际打开位置。

缓存用于复核和防止重复下载，不替代本次实际打开记录。分析前检查 `metadata.json` 与本次 `search_log` 的 source_id、版本和哈希；旧缓存只能作为候选线索，除非本次重新打开或用户明确要求复核该版本。引用必须指向实际读取的文件或网页位置。

只保存公开可访问、允许本地研究使用的文件；不绕过登录、付费墙、robots 或访问控制。不把下载全文提交到外部服务或公开发布。原始文件和哈希是审计辅助层，SQLite 仍是主数据源。

默认下载缓存位于 `artifacts/quantum-scout/cache/sources/<safe-source-id>/`；
显式传入 --workspace 时仍使用该运行目录内的 sources/，local_path 相对于此缓存/运行目录。

在线 PDF 使用 pdftotext 默认 reading_order，不使用可能将双栏逐行混排的 -layout。source.text_extraction 保存引擎/模式，页码、原始 PDF SHA256 及提取正文跨度继续保留；阅读顺序仍非版面语义保证；表格、公式和稀疏列涉及的证据须人工对照原 PDF 核对。没有实际人工核对记录时保持未核对，不将字符串门通过当成版面核对完成。旧正文与跨度不重写。
