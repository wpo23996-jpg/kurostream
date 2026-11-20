# 内部技术资料（不对外发布）

> 本文件随源码交付，用于维护与升级，请勿放入公开目录或客户可见的帮助中心。

## 频道 ↔ 适配器映射

`app/branding.py` 中的 `CATALOGUE` 定义对外频道 key 与适配器的对应关系：

| 公开 key | 前端显示 | 适配器文件 | 传输形态 | 播放 |
|---|---|---|---|---|
| `jp-hd` | 日本高清 | `providers/missav.py` | HTML(SSR) + packer 混淆 JS | HLS（需 Referer） |
| `jp-select` | 日本精选 | `providers/jable.py` | HTML，`var hlsUrl` 直出 | HLS |
| `asia` | 亚洲综合 | `providers/avple.py` | Next.js `__NEXT_DATA__` | HLS（部分相对路径受限） |
| `anime` | 动画专区 | `providers/hanime1.py` | HTML，`<source size>` 多清晰度 | MP4（支持 Range） |
| `western` | 欧美专区 | `providers/eporner.py` | 公开 JSON 搜索接口 | 仅元数据 |
| `archive` | 影片资料 | `providers/javbus.py` | HTML + 磁力表 | 无 |
| `rating` | 评分榜单 | `providers/javdb.py` | HTML + 磁力表 | 偶尔有预览流 |
| `series` | 系列合集 | `providers/supjav.py` | HTML，播放 token 加密 | 无 |

对外 API 只认公开 key，`branding.internal_key()` 负责反查。新增频道时：
1. 写 `providers/xxx.py`
2. 在 `providers/__init__.py` 的 `CLASSES` 里注册
3. 在 `branding.CATALOGUE` 里加一行（公开 key、显示名、文案）

## 各适配器关键实现点

**missav**：列表卡片 `div.thumbnail.group`；详情播放源被 Dean Edwards packer 包在
`eval(function(p,a,c,k,e,d){...})` 中，`providers/_packer.py` 负责解包，还原出
`source1280='https://<cdn>/<uuid>/1280x720/video.m3u8'`。分片实际是 TS 字节但扩展名 `.jpeg`，
代理层不做类型判断，直接透传。

**jable**：`var hlsUrl = '...'`，CDN 带 `bcdn_token` 与 `expires`，有效期数小时。

**avple**：数据在 `<script id="__NEXT_DATA__">`。注意 `pageProps.instance` 才是当前视频
（`pageProps.data` 是推荐列表）。`play` 字段可能是相对路径 `hls/<id>/playlist.m3u8`，
直连会被源站 403，只有绝对 URL 的条目可播。

**hanime1**：`<video><source src="...mp4?secure=...,<exp>" size="720">`，签名带过期时间，
所以详情必须实时抓、不能永久缓存（当前缓存 TTL 300s 足够）。

**javbus / javdb**：需要 `existmag=all` / `over18=1` Cookie 才能跳过年龄门，已在适配器里设置。

**supjav**：播放按钮的 `data-link` 是服务端加密串，需要逆向其前端解密逻辑才能拿到真实地址，
当前版本只提供元数据。

## 上游变更应对

| 现象 | 排查点 |
|---|---|
| 某频道 `items` 为空、`error` 为空 | 页面结构变了 → 检查 `_cards()` 的选择器 |
| `error` 含 `blocked 403` | Cloudflare 挑战 → 换 `KS_IMPERSONATE`，或在 `http_client.py` 加 Cookie |
| 详情 `no playable media` | 播放源签名/路径变化 → 检查 packer 解包结果或 `hlsUrl` |
| 播放 403 / 卡住 | 分片需要新 Referer → 检查 `Media.headers` 与 `config.IMAGE_REFERERS` |
| 图片空白 | 图片域名未进白名单 → 加 `config.allowed_media_hosts` + `IMAGE_REFERERS` |

## 扩容

- 多实例：外层 nginx `upstream` 轮询多个 `KS_PORT`，缓存与限速是进程内的，多实例会放大总 QPS，需相应调大 `KS_MIN_INTERVAL`。
- 分片缓存：nginx `proxy_cache_path` + `location /api/media/raw` 缓存 1–5 分钟，可显著降低回源。
- 出站代理：机房 IP 被封时设置 `KS_PROXY` 走住宅/海外出口。
