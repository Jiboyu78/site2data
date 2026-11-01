---
name: site2data
description: 网站结构解析与数据抓取的两阶段 skill：给定目标网站后全面解析页面层级、URL 模式聚类与内容分布，产出含站点架构图、关键数据节点、反爬策略分析的可视化报告（Markdown/Mermaid + 自包含 HTML/SVG）；用户指定数据项后按规格编写结构清晰、异常处理完善的 Python 爬虫并执行抓取（支持直接执行与生成独立可交付爬虫源码双路径）。适用于：分析网站结构、扒站点架构、生成站点地图报告、摸清反爬策略、定制字段抓取、批量爬元数据、生成 Python 爬虫、网站数据采集。触发词：网站结构分析、站点架构图、抓取元数据、写个爬虫、爬数据、站点侦察、反爬分析、批量抓取、scrape、crawl、site map。
agent_created: true
---

# site2data — 网站结构解析与数据抓取

两阶段流水线：**侦察（recon）→ 收割（harvest/codegen）**。
统一入口：`python scripts/site2data.py <命令>`（在技能根目录执行）；每条命令结束时 stdout 打印一行 JSON 摘要，回复用户前先读该摘要，如实汇报。

## 何时用

- 用户给出目标网站，想**看懂它**：结构、页面层级、有哪些数据、反爬情况；
- 用户想**抓数据**：指定字段（标题/价格/正文/列表…），要结构化结果或一份能跑的 Python 爬虫；
- 需要站点架构图 / 可视化侦察报告 / 抓取方案评估。

不适用：绕过验证码/付费墙/登录墙、抓取 robots.txt 或站点条款禁止的内容、未授权个人数据。

## 环境准备

```bash
pip install -r scripts/requirements.txt   # 核心：requests + beautifulsoup4
python scripts/site2data.py config        # 确认配置生效
```

配置三层（CLI > 工作区 site2data.config.json > 技能级 > 内置默认）详见 `references/config-guide.md`。

## 命令路由

| 命令 | 用途 | 关键参数 |
|---|---|---|
| `recon <URL>` | 站点结构侦察 + 可视化报告 | `--max-pages` `--max-depth` `--out` `--probe-rate` |
| `harvest <spec>` | 按数据规格执行抓取 | `--out` |
| `codegen <spec>` | 生成独立 Python 爬虫源码 | `-o crawler.py` |
| `validate <records.jsonl> <spec>` | 结果质量校验（字段填充率等） | |
| `config` | 查看生效配置 | |

## 阶段一：站点结构侦察（recon）

1. 运行 `python scripts/site2data.py recon <目标URL> [--max-pages 40 --max-depth 3]`。
   - 默认会先探测 `robots.txt` / sitemap.xml，并遵守 robots.txt；
   - 样本不足时提高 `--max-pages`；只关注某板块时把种子 URL 直接指到板块页。
2. 读取产物（`--out` 目录下）：
   - `report.md` — 主报告：概览、**站点架构图（Mermaid）**、URL 模式聚类、关键数据节点、反爬策略分析、抓取策略建议；
   - `report.html` — 自包含可视化报告（内联 SVG 架构图，浅色主题，可直接打开）；
   - `scan_result.json` — 机器可读全量数据。
3. 呈现给用户：
   - 把 `report.html` 与 `report.md` 交付给用户查看（打开预览或输出文件路径）；
   - 在回复中概述：页面规模、页面类型分布（列表/详情/JS 壳…）、反爬发现（严重度排序）、建议抓取模式（`list_detail` / `url_list`）与频率。
4. 解读反爬发现时对照 `references/anticrawl-playbook.md` 的「信号 → 判定 → 应对」表。
   限速试探仅在用户同意或明确要求时用 `--probe-rate` 开启（默认只做被动分析）。

## 阶段二：按需抓取（harvest / codegen）

1. **与用户对齐数据项**：抓哪些字段、从哪类页面（列表/详情）、大致数量、输出格式。拿不准时先提出字段清单让用户确认。
2. **编写 spec**（JSON 推荐）：依据 recon 报告的聚类与数据节点写选择器，schema 与示例见 `references/spec-schema.md`；示例参考 `examples/example-spec.json`。先小批：`limits.max_items: 10`。
3. **双路径执行**（按用户诉求选择；可并用）：
   - **直接抓取**：`python scripts/site2data.py harvest spec.json --out <目录>` → 产出 jsonl/csv + `run_summary.json` + `progress.json`（断点续跑：重跑同命令即续跑）；
   - **交付源码**：`python scripts/site2data.py codegen spec.json -o crawlers/xxx_crawler.py` → 生成结构清晰、异常处理完善的独立爬虫（仅依赖 requests+bs4，可脱离本 skill 运行；代码规范见 `references/codegen-spec.md`）。试跑 `python crawlers/xxx_crawler.py --limit 20 --out ./out`。
4. **校验**：`python scripts/site2data.py validate <records.jsonl> spec.json`。必填字段填充率 < 50% 时修选择器重抓，不静默接受。
5. **汇报**：读 `run_summary.json`，如实报告成功/失败/跳过条数与失败原因分布；失败项不隐瞒、不删除，单独列清单。

## 硬约定（合规与诚实）

- **robots.txt 与站点条款优先**：默认 `respect_robots=true`；被禁止的内容不抓。
- **不绕过**验证码、人机验证、付费墙、登录墙；需要登录态时由用户提供 Cookie（spec 的 `cookies` 键）。
- **礼貌速率**：默认 1 req/s，不并发轰炸；站点声明 Crawl-delay 时取更大值。
- **诚实汇报**：以 run_summary/validate 结果为准，失败与缺失如实呈现；缺陷单列清单，不静默过滤。
- **小批试跑再放量**：任何抓取先 10-20 条验证选择器与结构，再提高上限。

## 排障速查

| 症状 | 处理 |
|---|---|
| 页面为空/内容缺失 | 报告判为 `js_shell` → 找 JSON 接口写进 spec 的 `list.pages`，或走渲染通道（`references/ext-guide.md` 扩展点 5） |
| 403 / 挑战页 | 对照 anticrawl-playbook 的 WAF 段；补请求头/Cookie；仍失败则停止并如实告知 |
| 429 | 提高 `min_delay_seconds`，重试靠内置退避；勿加并发 |
| 字段大量 null | 选择器未命中 → 用 `scan_result.json` 里的 sample_urls 手工核对 DOM；调 `validate` 复查 |
| 批量中断 | 直接重跑同一 `harvest` 命令（progress.json 续跑） |
| 生成爬虫行为异常 | 优先改内嵌 SPEC；spec 大改则重新 codegen（见 codegen-spec） |

## 扩展

新增探测器/导出格式/字段变换/渲染通道/CLI 命令的挂接方式见 `references/ext-guide.md`。

## Agent 检查清单

```
□ 依赖可用（pip install -r scripts/requirements.txt）；config 确认限速与 robots 设置
□ 阶段一：recon 出报告 → 交付 report.html / report.md → 概述结构/数据节点/反爬/建议
□ 阶段二：与用户对齐字段清单 → 写 spec（小批量）→ harvest 或 codegen → validate → 读 run_summary 如实汇报
□ 抓取遵守 robots 与红线；--probe-rate 仅显式同意时用
□ 失败项单列清单；填充率不足先修选择器再放量
```
