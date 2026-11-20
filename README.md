# KuroStream

**视频聚合播放平台 · 可私有化部署的流媒体站点**

KuroStream 是一套开箱即用的影视站点程序：自带内容索引、统一搜索、HLS 播放代理与响应式前端，
一条命令部署到任意 Linux 服务器或 Docker 环境，即可对外提供在线播放服务。

---

## 功能

| 模块 | 说明 |
|---|---|
| 统一搜索 | 多频道并行检索，毫秒级聚合返回 |
| 频道首页 | 最新 / 热门 / 中文字幕 三种信息流 |
| 详情页 | 标题、演员、标签、发行信息、下载链接 |
| 在线播放 | 原生 `<video>` + hls.js，支持清晰度切换、进度拖动 |
| 流媒体代理 | 服务端重写 HLS 清单与分片，解决跨域、防盗链、Referer 校验 |
| 图片代理 | 封面统一走站点代理，客户端零外链 |
| 多级缓存 | 内存 TTL 缓存，重复请求不打穿后端 |
| 品牌可配 | 站点名、副标题、频道名均可通过环境变量配置 |
| 无状态 | 单进程即可运行，可水平扩多实例 |

前端没有任何第三方依赖（hls.js 已内置到 `web/vendor/`），断网 CDN 也能跑。

---

## 频道体系

站点对外以「频道」组织内容，共 8 个频道，全部可在前端切换或混合展示：

```
日本高清 · 日本精选 · 亚洲综合 · 动画专区 · 欧美专区 · 影片资料 · 评分榜单 · 系列合集
```

每个频道可以单独关闭：编辑 `app/providers/__init__.py` 的 `CLASSES` 即可。

---

## 部署

### 方式一：一键脚本（Debian / Ubuntu，推荐）

```bash
# 上传 zip 并解压
unzip kurostream-v1.0.0.zip -d kurostream && cd kurostream

# 安装（自动配置 systemd + nginx + venv）
sudo bash deploy/install.sh your-domain.com
```

脚本会完成：系统依赖 → 运行用户 → 代码部署到 `/opt/kurostream` → venv 与依赖 →
`/etc/kurostream/env` → systemd 服务 → nginx 反代 → 健康检查。

装好后：

```bash
systemctl status kurostream          # 服务状态
journalctl -u kurostream -f          # 实时日志
systemctl restart kurostream         # 改完配置后重启
```

### 方式二：Docker

```bash
cp .env.example .env        # 按需修改
docker compose up -d --build
docker compose logs -f
```

端口默认 `8000`，前面可自行挂 nginx / Caddy 做 HTTPS。

### 方式三：手动

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
KS_HOST=0.0.0.0 KS_PORT=8000 python run.py
```

前置要求：Python 3.10+，能出网。

---

## 配置项

所有配置走环境变量（systemd 读 `/etc/kurostream/env`，Docker 读 `.env`）。

| 变量 | 默认 | 说明 |
|---|---|---|
| `KS_HOST` | `127.0.0.1` | 监听地址（容器内用 `0.0.0.0`） |
| `KS_PORT` | `8000` | 监听端口 |
| `KS_WORKERS` | `1` | uvicorn worker 数，建议 = CPU 核数 |
| `KS_SITE_NAME` | `KuroStream` | 站点名（前端标题） |
| `KS_TAGLINE` | `高清片库 · 极速播放` | 副标题 |
| `KS_MIN_INTERVAL` | `0.35` | 单频道最小请求间隔（秒），调大可降低对上游压力 |
| `KS_TIMEOUT` | `30` | 上游超时（秒） |
| `KS_RETRIES` | `3` | 上游重试次数 |
| `KS_CACHE_TTL` | `300` | 缓存有效期（秒） |
| `KS_PROXY` | 空 | 出站代理，形如 `http://user:pass@host:port` |
| `KS_LOG_LEVEL` | `info` | 日志级别 |

改完 `systemctl restart kurostream` 生效。

---

## 手机端

三种交付方式，同一套后端：

| 方式 | 成本 | 能上架 | 说明 |
|---|---|---|---|
| **PWA** | 0 | ✗ | 服务器已自带。手机浏览器「添加到主屏幕」，全屏无地址栏 |
| **Android APK** | 约 1 小时 | ✓ | `mobile/` 目录，Capacitor 工程 |
| **iOS IPA** | 需要 Mac | ✓ | 同一工程，`npx cap add ios` |

### PWA（开箱可用）

部署到 HTTPS 后：
- Android Chrome → 菜单 →「安装应用」
- iOS Safari → 分享 →「添加到主屏幕」

已内置 `manifest.webmanifest`、`sw.js`（只缓存外壳，API 与分片直连）、全套图标。

### 原生外壳

```bash
cd mobile
npm install
KS_SERVER=https://你的域名.com npm run sync:web   # 生成 www 并注入 API 地址
npx cap add android && npx cap sync android && npx cap open android
```

**关键：服务端必须配 `KS_PUBLIC_BASE`**，否则壳里的播放地址仍是相对路径，会指向 `capacitor://localhost` 导致黑屏：

```bash
# /etc/kurostream/env
KS_PUBLIC_BASE=https://你的域名.com
systemctl restart kurostream

curl https://你的域名.com/api/health
# {"ok":true,...,"public_base":"https://你的域名.com"}   ← 有值才算生效
```

详细构建步骤见 `mobile/README.md`。

---

## 页面与路由

单页应用，hash 路由，服务器不需要任何 rewrite 配置：

| 路由 | 页面 |
|---|---|
| `#/` | 首页，各频道横排（Netflix 式横向滚动） |
| `#/c/{channel}` | 频道网格，支持排序与「加载更多」 |
| `#/s/{关键词}` | 搜索结果，按频道分组 |
| `#/v/{channel}/{id}` | 详情 + 播放器 + 相关推荐 |
| `#/saved` | 我的收藏（本地） |
| `#/terms` · `#/privacy` · `#/about` | 用户协议 / 隐私政策 / 关于 |

体验细节：

- **渐进加载**：首页每个频道独立请求，先返回的先上屏，不等最慢的
- **骨架屏**：加载中显示占位块，不是白屏
- **播放器**：hls.js 自适应重试、画质切换保留进度、进度自动记忆（下次接着看）
- **快捷键**：`空格` 播放/暂停、`←/→` 快退快进 10 秒、`F` 全屏
- **移动端**：390px 下顶栏、频道条、卡片全部适配，无横向溢出
- **空态/错误态**：每个页面都有对应的提示与重试入口

---

## 会员与收款

站点自带会员体系与订单闭环，无需额外系统即可开卖。

### 档位

| 档位 | 价格 | 时长 | 画质 | 设备 | 下载 |
|---|---|---|---|---|---|
| 游客 | 免费 | — | 480p · 每日 5 部 | 1 | ✗ |
| 周卡 | ¥15 | 7 天 | 1080p | 1 | ✗ |
| 月卡 | ¥39 | 30 天 | 1080p | 2 | ✗ |
| 年卡 | ¥299 | 365 天 | 1080p | 3 | 每日 10 部 |
| 终身 | ¥699 | 永久 | 1080p | 3 | 每日 10 部 |

### 收款流程

```
用户点「立即开通」→ 生成订单（pending）
  → 页面显示收款账号 + 备注订单号
  → 用户付款后点「我已完成支付」（claimed）
  → 你确认到账后执行一条命令（paid）
  → 会员立即生效，前端轮询自动解锁
```

确认到账只需一条命令：

```bash
curl -X POST http://127.0.0.1:8000/api/admin/order/KS26112003323244184/confirm \
     -H "X-Admin-Token: $KS_ADMIN_TOKEN"
```

查看经营数据：

```bash
curl http://127.0.0.1:8000/api/admin/stats -H "X-Admin-Token: $KS_ADMIN_TOKEN"
# {"paid_orders": 12, "revenue": 1588.0, "members": 12, "pending_orders": 1}
```

### 配置

在 `/etc/kurostream/env`（或 `.env`）里填：

```bash
KS_PAY_ALIPAY=https://qr.alipay.com/xxxx   # 收款码链接
KS_PAY_USDT=Txxxxxxxxxxxxxxxxxxxxxxxxxxxx  # USDT-TRC20 地址
KS_ADMIN_TOKEN=<随机字符串>                 # 后台令牌，必须设置
```

填了哪个渠道，定价页就显示哪个。**未设置 `KS_ADMIN_TOKEN` 时后台接口一律 503。**

### 关键接口

| 端点 | 说明 |
|---|---|
| `GET /api/me` | 当前访客会员状态、今日额度、最近订单 |
| `GET /api/plans` | 档位 + 已开通的支付渠道 |
| `POST /api/order` | 下单，body `{tier, channel}` |
| `GET /api/order/{no}` | 查订单（前端轮询用） |
| `POST /api/order/{no}/claim` | 用户声明已付款 |
| `POST /api/admin/order/{no}/confirm` | 管理员确认到账（需 `X-Admin-Token`） |
| `GET /api/admin/stats` | 收入/会员/待确认统计 |

### 判定逻辑

- 会员等级**只在服务端判定**，客户端传什么都没用
- 免费用户每打开一次详情计一次额度（5 次/天），超出返回 `402 quota_exhausted`，前端自动弹定价页
- 会员到期自动降级，无需定时任务
- 续费是**叠加**而非覆盖：月卡到期前再买，从原到期日往后加
- 终身会员设为永久，后续任何续费都不会缩短

---

## API

| 端点 | 参数 | 说明 |
|---|---|---|
| `GET /api/health` | — | 存活检查 |
| `GET /api/providers` | — | 频道列表与能力 |
| `GET /api/search` | `q`、`provider`、`page` | 聚合搜索，按频道分组 |
| `GET /api/browse` | `provider`、`page`、`sort` | 信息流（new/trending/chinese） |
| `GET /api/detail` | `provider`、`id` | 详情 + 可播放地址 |
| `GET /api/media/hls` | `u`、`r` | HLS 清单（服务端重写） |
| `GET /api/media/raw` | `u`、`r` | 分片 / mp4 转发，支持 Range |
| `GET /api/img` | `u`、`r` | 封面代理 |

交互式文档：`/api/docs`。

`provider` 取值就是频道 key：`jp-hd`、`jp-select`、`asia`、`anime`、`western`、`archive`、`rating`、`series`，或 `all`。

---

## 架构

```
浏览器
  │  /api/search  /api/detail  /api/media/hls
  ▼
FastAPI (app/main.py)
  ├── 频道路由       providers/        8 个频道适配器，统一 BaseProvider 接口
  ├── 媒体代理       proxy.py          m3u8 重写 + host 白名单（防 SSRF）
  ├── 传输层         http_client.py    TLS 指纹会话、限速、重试、Cloudflare 兼容
  └── 缓存           cache.py          TTL 缓存
```

播放链路：

1. 详情解析得到播放清单地址
2. `/api/media/hls` 带正确请求头拉取清单，把每行 URI、`#EXT-X-KEY`、`#EXT-X-MAP`、
   master 的 variant 全部改写为本站 `/api/media/raw?u=...`
3. 浏览器只访问同源地址，分片由服务端转发并透传 `Range`
4. 结果：无跨域、无防盗链、可拖动进度

安全：代理仅放行白名单域名，拒绝私网 / 回环地址，避免被当作 SSRF 跳板。

---

## 运维建议

- **进程数**：`KS_WORKERS` 设为 CPU 核数；单 worker 约可承载 200 并发播放（分片转 IO 型）。
- **带宽**：1080p 单路约 3–6 Mbps，按 `并发数 × 5 Mbps` 预留。
- **前置缓存**：高并发场景建议在 nginx 加 `proxy_cache` 缓存分片，或上 CDN 回源到本站。
- **监控**：`/api/health` 可直接接 uptime 监控；频道异常会体现在响应里的 `error` 字段。
- **升级**：替换 `/opt/kurostream/app` 与 `web` 后 `systemctl restart kurostream`，配置在
  `/etc/kurostream/env` 不受影响。

---

## 目录

```
kurostream/
├── app/
│   ├── main.py            HTTP 接口与媒体代理入口
│   ├── proxy.py           HLS 重写 / 白名单
│   ├── http_client.py     传输层（指纹、限速、重试）
│   ├── config.py          配置与品牌
│   ├── branding.py        频道公开展示映射
│   ├── cache.py           缓存
│   ├── schemas.py         数据结构
│   └── providers/         8 个频道适配器
├── web/                   前端（index.html / app.js / style.css / vendor/hls.min.js）
├── deploy/
│   ├── install.sh         一键安装
│   ├── kurostream.service systemd
│   └── nginx.conf         反向代理
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
└── run.py
```

---

## 许可

商用授权版本，允许部署于自有或客户服务器并对外运营。
未经授权不得二次分发源代码或作为模板出售。技术细节见 `docs/INTERNAL.md`（内部资料）。
