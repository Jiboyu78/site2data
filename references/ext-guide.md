# 扩展指南（ext-guide）

site2data 按领域分包，扩展点集中在以下五处。约定：**新增能力放新文件 + 在路由/注册表挂接**，不改既有函数签名。

## 1. 新增反爬探测器

- 位置：`scripts/site2data_lib/recon/anticrawl.py`
- 注册：在 `analyze()` 的 `_passive_findings()` 中追加一个探测函数，返回 `Finding(category, severity, evidence, recommendation)`。
- 建议：只做被动指纹/行为观察；任何主动试探必须像 `probe_rate` 一样**显式开关**。

## 2. 新增数据节点识别

- 位置：`scripts/site2data_lib/recon/datanodes.py`
- 注册：在 `extract()` 末尾追加 `nodes.extend(_your_extractor(soup))`，返回 `DataNode` 列表。
- 例子：识别 `<script id="__NEXT_DATA__">` 里的 JSON 字段、OpenAPI 文档链接、内嵌 GraphQL 查询。

## 3. 新增导出格式

- 位置：`scripts/site2data_lib/export/writers.py`
- 注册：新增 `write_xxx(records, path)`，在 `write_all()` 的分派中加一个 `if "xxx" in formats`。
- 配置联动：`formats` 配置数组直接可选新格式名。

## 4. 新增字段变换（transform）

- 两处保持语义一致：`crawl/runner.py::_transform` **和** `assets/templates/crawler_template.py.tpl::_transform`（生成物自带副本）。
- 新变换命名建议动词（`date`、`abs_url`、`dedupe`）；带参数用 `name:arg` 形式（参考 `regex:<pat>`）。

## 5. 新增渲染通道（Playwright / 接口抓取）

- 建议实现为 `scripts/site2data_lib/recon/render.py`：导出 `fetch_rendered(url) -> html`，供 `structure.crawl` 与 `runner` 复用。
- 接口抓取（更优）：无需新代码——把接口 URL 写进 spec 的 `list.pages`，字段选择器换成 JSON 路径时可加 `kind: "jsonpath"` 变换（属扩展点 4）。
- 配置联动：新增配置键 `render: "never" | "auto" | "always"`（`core/config.py::DEFAULTS`）。

## 命令扩展

- `scripts/site2data.py` 的 `COMMANDS` 元组加名字，`scripts/site2data_lib/cli.py` 加 `cmd_<name>(argv, skill_root)` 函数即可。
- 约定：结束时 stdout 打印一行 JSON 摘要（`{"command": ..., ...}`），供 agent 读取。

## 测试建议

- 纯函数（url_pattern、_transform、validate_records）用 `pytest` 直接测；
- 网络路径用 `examples/example-spec.json` 指向 `https://books.toscrape.com/`（公开练手站）做集成回归；
- 生成物回归：`codegen` 后 `py_compile` + 小样本 `--limit 3` 跑通即视为健康。
