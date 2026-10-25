# 反爬策略库（anticrawl-playbook）

> 用途：解读 recon 报告中的反爬发现，并选择应对策略。
> **红线**：不绕过验证码/人机验证/付费墙；不伪造授权；只在公开且 robots 允许的数据上作业。

## 信号 → 判定 → 应对

| 信号 | 判定 | 应对 |
|---|---|---|
| `Server`/响应头含 `cf-ray`、`__cfduid` | Cloudflare 防护 | 低频 + 稳定 UA/Cookie 会话；出现 JS Challenge 时改 Playwright 渲染通道；**不要**尝试破解挑战 |
| `akamai`/`ak_bmsc` | Akamai | 保持会话粘性（同一 Session 顺序抓）；避免并发 |
| `incap_ses`/`incapsula` | Incapsula | 同上；优先找官方 API/RSS |
| 大量 403 | WAF/UA 拦截 | 补齐浏览器常见头（Accept、Accept-Language、Referer）；换 UA 族；仍失败则停下并如实告知 |
| 429 / `Retry-After` | 限流 | `min_delay_seconds ≥ 1.5`；遵守 Retry-After；指数退避（site2data 已内置） |
| `X-RateLimit-*` | 配额制 | 按剩余配额排程；跨日续跑（progress.json 断点续跑支持） |
| 空页面 + `__NEXT_DATA__`/`id="root"` | SPA/JS 壳 | ① DevTools Network 找 JSON 接口（最优）② Playwright 渲染（`--render` 通道，扩展点） |
| 登录墙（请登录/password） | 需登录态 | 由用户提供 Cookie/会话；不绕过登录 |
| robots `Crawl-delay` | 站点声明 | `min_delay_seconds ≥ 该值`；尊重 `Disallow` |
| 页面内容随机缺失 | 蜜罐/风控升级 | 降低频率、固定 UA/会话；间隔随机抖动 |

## 速率试探（显式开启）

`recon --probe-rate` 仅发 **2 次**短时连发请求，观察是否 429：
- 触发 429 → 站点对短时并发敏感 → 串行 + ≥1.5s 间隔；
- 未触发 → 从 1 req/s 起步，按稳定性微调（仍建议保守）。

## 技术选型：三通道

| 通道 | 适用 | 实现 |
|---|---|---|
| **静态 requests** | 服务端渲染（默认） | site2data harvest / 生成的爬虫 |
| **JSON 接口** | SPA、列表分页接口 | 把接口 URL 直接写进 spec 的 `list.pages`（最稳） |
| **Playwright 渲染** | JS 壳、强风控 | 扩展点（ext-guide.md），生成代码后手工接入 |

**选型顺序**：接口 > 静态 > 渲染（成本与风险递增）。

## 工程防御清单（生成爬虫已内置）

- [x] 全局限速（最小请求间隔）
- [x] 指数退避 + 抖动 + Retry-After
- [x] 429/5xx 重试、4xx 不重试
- [x] robots.txt 门禁（harvest 通道）
- [x] 逐条异常隔离（单条失败不中断批次）
- [x] 断点续跑（progress.json）
- [x] run 摘要诚实汇报（成功/失败/错误分布）
