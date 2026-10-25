# 数据规格 Schema（spec-schema）

spec 描述"抓什么"，是阶段二的核心交付物。**由 agent 根据用户指定的数据项 + recon 报告编写**，
然后交给 `harvest`（直接执行）或 `codegen`（生成独立爬虫）。

格式：JSON（零依赖，推荐）或 YAML（需 PyYAML）。完整示例见 `examples/example-spec.json`。

## 顶层结构

```jsonc
{
  "name": "books_demo",          // 必填：任务名（也是输出文件名前缀，用字母数字下划线）
  "mode": "list_detail",         // list_detail | url_list | detail_only
  "list": { ... },               // URL 来源（三种模式都需要）
  "detail": { "fields": { ... } }, // 必填：字段提取规则
  "headers": { "Referer": "..." }, // 可选：附加请求头
  "cookies": { "session": "..." }, // 可选：登录态
  "limits": { "max_items": 100, "delay_seconds": 1.0 },
  "output": { "name": "books_demo", "formats": ["jsonl", "csv"] }
}
```

## mode 三种模式

| 模式 | 场景 | URL 来源 |
|---|---|---|
| `list_detail` | 列表页发现链接 → 详情页抽字段（最常见） | `list.url` / `list.pages` / `list.template` + 分页 |
| `url_list` | 已有一批目标 URL，逐条抽字段 | `list.pages` 或 `list.template` |
| `detail_only` | 同 url_list（语义强调：无列表层） | 同上 |

## list（URL 来源与发现）

```jsonc
{
  "url": "https://example.com/list",          // 单页
  "pages": ["https://a", "https://b"],        // 或显式 URL 列表
  "template": "https://example.com/p{page}",  // 或分页模板
  "pagination": { "start": 1, "end": 5, "step": 1 },  // 或 {"pages": [1,3,7]}
  "item_selector": "article.item",  // 列表页内条目范围（可选）
  "link_selector": "h3 a",          // 条目内指向详情的链接（list_detail 必备其一与 item_selector）
  "link_attr": "href"               // 默认 href
}
```

## detail.fields（字段提取规则）

```jsonc
{
  "title":  { "selector": "h1", "kind": "text", "transform": "strip" },
  "price":  { "selector": ".price", "kind": "text", "transform": "regex:([0-9.]+)" },
  "img":    { "selector": "img.main", "kind": "attr", "attr": "src" },
  "body":   { "selector": "article", "kind": "html" },
  "upc":    { "selector": "table tr:nth-child(1) td", "optional": true }
}
```

| 键 | 必填 | 说明 |
|---|---|---|
| `selector` | ✔ | CSS 选择器（bs4 `select_one` 语义） |
| `kind` | | `text`（默认）/ `html` / `attr` |
| `attr` | kind=attr 时 ✔ | 属性名，如 `href`、`src` |
| `transform` | | `strip` `lower` `upper` `number` `join` `regex:<pat>`（取 group1） |
| `optional` | | `true` 时校验不计入必填（validate 宽容） |

字段名约束：合法 Python 标识符（字母/数字/下划线，不以数字开头）——生成的爬虫会用作 dataclass 字段。

## limits / output

- `limits.max_items`：抓取条数上限（**默认保守 100**；全量前先小批试跑）
- `limits.delay_seconds`：请求间隔（取与配置 `min_delay_seconds` 的较大值）
- `output.formats`：`jsonl` / `csv` / `json` / `md` 任意组合

## 编写流程（agent 指南）

1. 读 recon 报告（`report.md`）第 3、4 节：URL 模式聚类 + 关键数据节点；
2. 用 `sample_urls` 里的真实 URL 核对选择器（可用 `curl` 或 WebFetch 抽查）；
3. 字段选择器宁可"具体到唯一"，避免 `div.text` 这类宽泛命中；
4. 先写小 spec（`max_items: 10`）→ `harvest` 试跑 → `validate` 看填充率；
5. 填充率 < 50% 的必填字段要修选择器，不要静默接受。

## 常见坑

- 列表页 `link_selector` 要在 `item_selector` 作用域内命中（runner 在条目 scope 内 `select_one`）；
- 分页模板占位符固定为 `{page}`；
- 详情页字段提取失败时记录值为 `null`（不抛异常），用 `validate` 统计填充率发现选择器问题；
- `transform=regex:...` 反斜杠在 JSON 中要写双份（`"regex:([0-9.]+)"` 无转义则原样即可）。
