# 配置说明（config-guide）

site2data 采用**三层配置**，优先级从低到高：

1. **代码内置默认**（`site2data_lib/core/config.py` 的 `DEFAULTS`）
2. **技能级配置**：技能根目录 `site2data.config.json`（用户说"以后默认…"时改这里）
3. **工作区覆盖**：当前工作目录 `site2data.config.json`（随项目走，勿提交敏感信息）
4. **环境变量**：`SITE2DATA_*`（少量高频键）
5. **CLI 参数**：每次调用显式指定（最高优先级）

查看当前生效值：

```bash
python scripts/site2data.py config
```

## 全部配置键

| 键 | 默认值 | 说明 |
|---|---|---|
| `user_agent` | `site2data/1.0 (+polite…)` | UA；建议保留礼貌标识与联系方式 |
| `timeout` | `15.0` | 单请求超时（秒） |
| `max_retries` | `3` | 网络错误/429/5xx 最大重试次数 |
| `backoff_factor` | `1.5` | 指数退避基数（`1.5 × 2^attempt` + 抖动） |
| `min_delay_seconds` | `1.0` | **全局请求最小间隔**（礼貌速率，建议 ≥1s） |
| `headers` | `{}` | 附加请求头（如 `Cookie`、`Referer`） |
| `proxy` | `""` | 代理 URL，如 `http://127.0.0.1:7890` |
| `max_pages` | `40` | recon 最大页面样本数 |
| `max_depth` | `3` | recon 最大爬行深度 |
| `respect_robots` | `true` | robots.txt 门禁（硬约定默认开启） |
| `parser` | `html.parser` | bs4 解析器；装有 lxml 可改 `"lxml"` |
| `probe_rate` | `false` | 限速试探开关（默认关闭，CLI `--probe-rate` 开启） |
| `harvest_max_items` | `100` | harvest 默认条数上限（spec.limits 可覆盖） |
| `harvest_delay_seconds` | `1.0` | harvest 默认请求间隔 |
| `output_dir` | `site2data_out` | 默认输出根目录 |
| `formats` | `["jsonl","csv"]` | 导出格式（可加 `json`、`md`） |

## 环境变量

| 环境变量 | 映射键 |
|---|---|
| `SITE2DATA_USER_AGENT` | `user_agent` |
| `SITE2DATA_TIMEOUT` | `timeout` |
| `SITE2DATA_MIN_DELAY` | `min_delay_seconds` |
| `SITE2DATA_PROXY` | `proxy` |
| `SITE2DATA_OUTPUT_DIR` | `output_dir` |

## 依赖管理

```bash
pip install -r scripts/requirements.txt
```

- **核心依赖**：`requests`、`beautifulsoup4`（recon/harvest/codegen 产物均只依赖这两个）
- **可选**：`lxml`（更快解析）、`PyYAML`（YAML spec；JSON spec 零额外依赖）
- 生成的独立爬虫同样只需 `requests` + `beautifulsoup4`，可拷贝到任意环境运行。

## 典型调优

| 场景 | 建议 |
|---|---|
| 站点敏感 / 明确限速 | `min_delay_seconds: 2.0`，`max_retries: 5` |
| 内网/代理环境 | 配置 `proxy`，或先 `curl` 验证连通性 |
| 大站只看结构 | `max_pages: 20`，`max_depth: 2`（够用且快） |
| 深挖单板块 | 把种子 URL 直接指到该板块（比加 depth 更高效） |
