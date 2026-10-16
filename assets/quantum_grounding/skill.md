# Quantum grounding

调用 `execute(params, ctx)` 校验本次已打开全文中的引文存在性。
输入和输出契约见同目录 `manifest.yaml`、`executor.py`。

先逐字匹配，再折叠空白，最后尝试提取格式白名单（可组合）：
- 多空白/换行/制表符折叠为单个空格。
- 移除 U+00AD 软连字符、U+200B 零宽空格和 U+FEFF BOM；不移除 ZWJ/ZWNJ。
- 仅合并 ASCII 字母间的 `字母-换行小写字母`（允许 CRLF 与换行两侧水平空白）。

不做 NFKC、大小写转换、数字转换（含全角数字/上下标）、标点替换、否定词删改或 OCR 纠错。
换行连字符合并只是提取层定位；可能有语义歧义，仍须双审，不据此认定语义支持。
`method` 与 `normalization_methods` 记录匹配所用转换；`matched_text` 与半开 `span=[start,end]`
始终指向原始提取文本，折叠空白映射覆盖整个原始空白区间。失败候选完整进入 grounding_failures。
模糊匹配只能辅助人工定位，不能自动放行 OCR 错字或近似引文。
字符偏移和 SHA256 针对传入的 UTF-8 提取文本，不是 PDF 原件字节。
提供结构化 segments 时，主引文只能在声明 location 的唯一原始分段内匹配，search_span 不能越出该段；位置缺失或原文映射歧义则拒绝。

`validated_candidates` 仍需语义支持和页/节位置核查。返回 `facts=[]`，
防止 SearchOS 的 URL dispatcher 将字符串检查结果直接作为事实入图。
这不是全局中间件：只有显式调用才生效，其他 SearchOS 抽取路径不会自动拦截。

调用方必须持久化全部 `grounding_failures` 到批次审计数组；不得静默丢弃。
未找到引文的候选不能进入问题定义、准入、评分或非空定量证据。
语义复核不支持结论时，另记 `semantic_mismatch`，字段保留缺失/不确定。
