# 生成爬虫规范（codegen-spec）

`codegen` 生成的独立爬虫是**交付级源码**：结构清晰、异常处理完善、可脱离 site2data 运行。
模板：`assets/templates/crawler_template.py.tpl`（占位符 `{{SPEC_JSON_STR}}` / `{{RECORD_FIELDS}}` / `{{GENERATED_AT}}` / `{{NAME}}` / `{{FILENAME}}`）。

## 代码结构（模板固定分区）

```
模块 docstring（用法、设计说明）
├── SPEC                    # 内嵌数据规格（json.loads 字符串字面量，避免 JSON/Python 字面量差异）
├── 错误类型                 # CrawlError → FetchError / ParseError（细分便于排障）
├── Record (@dataclass)     # 字段由 spec 注入；_url/_status 元数据
├── 网络层                  # build_session / fetch（限速+指数退避+Retry-After）/ get_soup
├── 字段抽取                # _transform / extract_field / parse_detail
├── URL 发现                # list_page_urls / iter_detail_urls（三模式）
├── 检查点与导出             # load_progress / save_progress / write_outputs（jsonl+csv）
└── 主流程                  # run（逐条隔离 + 摘要）/ main（argparse CLI）
```

## 异常处理约定

| 层 | 策略 |
|---|---|
| 网络层 | 网络错误/429/5xx → 指数退避重试（默认 3 次）；重试耗尽抛 `FetchError` |
| HTTP 状态 | 非 200 且非重试类 → 立即抛 `FetchError`（记入失败清单） |
| 解析层 | bs4 容错解析；彻底失败抛 `ParseError` |
| 字段抽取 | 单字段异常 → 该字段置 `None`，**不拖垮整条记录** |
| 记录层 | 单条失败 → 记 `progress.failed`，继续批次（逐条隔离） |
| 批次层 | 中断后重跑同命令即续跑（`progress.done` 跳过） |

## CLI 接口（生成物自带）

```bash
python <name>_crawler.py --limit 20 --out ./out   # 试爬 20 条
python <name>_crawler.py --limit 0 --out ./out    # 按 SPEC 上限全量
python <name>_crawler.py --out ./out --no-resume  # 忽略进度重抓
```

退出码：`0` 全部成功；`1` 存在失败项。stdout 打印 run 摘要 JSON。

## Python 最佳实践清单（模板已满足）

- `from __future__ import annotations` + 类型标注（dataclass、`Iterator`、`dict[str, Any]`）
- 标准库分区导入；第三方仅 requests / bs4
- logging 而非 print（摘要 JSON 例外，供 agent 读取）
- argparse 带 `--help` 说明
- 魔法数进 SPEC/常量；无全局可变状态（除 progress 字典显式传参）
- JSON 持久化用 `ensure_ascii=False` + `indent=2`

## 修改生成物的两种方式

1. **改 SPEC 字典**（顶部）—— 调整字段/选择器/限额，无需改逻辑；
2. **回 skill 重新 codegen** —— spec 变更后重新生成，避免手改漂移。
