# iOS 打包完整指南（Windows 也能做）

iOS 的硬约束：**编译必须在 macOS 上**。你没有 Mac，所以走云端。

三条路，按预算选：

| 路径 | 费用 | 装到 iPhone | 上架 App Store |
|---|---|---|---|
| **A. GitHub Actions + Sideloadly** | 0 | ✅ 7 天有效期 | ❌ |
| **B. Codemagic 免费 Apple ID** | 0 | ✅ 7 天有效期 | ❌ |
| **C. 付费开发者账号** | $99/年 | ✅ 1 年 | ✅ |

先走 A 或 B 把 App 跑起来，确认体验没问题，再决定要不要花 $99。

---

## 路径 A：GitHub Actions 出包（零成本，推荐先试）

公开仓库的 `macos-14` runner **完全免费**，不需要 Apple 账号。

### 1. 推代码到 GitHub

```bash
cd kurostream
git init && git add . && git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的用户名/kurostream.git
git push -u origin main
```

### 2. 触发构建

仓库 → `Actions` → 左侧选 **Build iOS (unsigned ipa)** → 右侧 `Run workflow`：

| 输入 | 填什么 |
|---|---|
| `server_url` | `https://你的域名.com`（必须 https） |
| `app_name` | `KuroStream` |
| `bundle_id` | `com.你的名字.kurostream`（不能和苹果商店里已有的重复） |

点绿色按钮，等 8-15 分钟（macOS runner 比 Linux 慢）。

### 3. 下载产物

运行成功后，页面底部 **Artifacts** → `kurostream-ios-unsigned-1.zip` → 解压得到 `KuroStream-unsigned.ipa`。

### 4. 装到 iPhone（Windows 就能做）

**准备：**

- 下载 [iTunes](https://www.apple.com/itunes/)（Windows 版，提供 Apple 驱动）
- 下载 [Sideloadly](https://sideloadly.io)（免费）

**步骤：**

1. iPhone 用数据线连电脑，手机上点「信任」
2. 打开 Sideloadly，左上角会识别到设备
3. 把 `KuroStream-unsigned.ipa` 拖进 Sideloadly
4. `Apple ID` 填你的任意 Apple ID（免费账号就行）
5. 点 `Start`，输入 Apple ID 密码
6. 手机上：`设置 → 通用 → VPN与设备管理 → 开发者应用` → 点你的 Apple ID → 「信任」

**限制：**

- 免费 Apple ID 签名的 App **7 天后失效**，重新拖一次 Sideloadly 即可（数据不丢）
- 每台设备最多同时存在 **3 个**免费签名 App
- 每 7 天最多签 **10 次**

**想免去 7 天折腾** → 用 [AltStore](https://altstore.io)：电脑装 AltServer，Wi-Fi 同网段时自动续签。

---

## 路径 B：Codemagic（更简单，能自动签名）

Codemagic 免费层 **500 macOS M2 分钟/月**，自带 Apple 账号托管，界面上传 Apple ID 就能出可安装的 dev 包。

### 步骤

1. 注册 <https://codemagic.io>，用 GitHub 账号登录
2. `Add application` → 选你的仓库
3. 构建配置选 **Use codemagic.yaml**（项目根目录已有）
4. 左侧 `Environment variables` 加一条：

```
KS_SERVER = https://你的域名.com
```

5. `Teams` → `Integrations` → `Developer Portal` → 用 Apple ID 登录（免费账号也行）
6. `Start new build` → 选 **iOS IPA（需绑定 Apple 账号）**

Codemagic 会自动：拉取开发证书 → 注册你的设备 UDID → 生成描述文件 → 编译 → 出 ipa。

产物在构建页面 `Artifacts` 里直接下载，用 Sideloadly 装（或 Xcode Devices 窗口拖进去）。

> 免费 Apple ID 同样 7 天限制。要突破限制只能上付费开发者账号。

---

## 路径 C：付费开发者账号（$99/年）

有账号之后：

1. Apple Developer 后台创建：
   - App ID（Bundle ID 要和 `bundle_id` 一致）
   - Distribution Certificate（.p12）
   - Provisioning Profile（App Store 或 Ad Hoc）
2. 三个都转 base64：

```bash
# macOS / Linux
base64 -w0 cert.p12 > cert.b64
base64 -w0 profile.mobileprovision > prov.b64

# Windows (PowerShell)
[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.p12")) | Out-File cert.b64
```

3. GitHub 仓库 → `Settings` → `Secrets and variables` → `Actions`，建 6 个 secret：

| Secret | 内容 |
|---|---|
| `IOS_CERT_P12_BASE64` | cert.b64 全部内容 |
| `IOS_CERT_PASSWORD` | 导出 p12 时设的密码 |
| `IOS_PROVISION_BASE64` | prov.b64 全部内容 |
| `IOS_TEAM_ID` | 10 位 Team ID（开发者后台右上角） |
| `IOS_BUNDLE_ID` | `com.你的名字.kurostream` |
| `IOS_KEYCHAIN_PASSWORD` | 随便设，比如 `temp123456` |

4. `Actions` → **Build iOS (signed ipa)** → 选分发方式：
   - `development` → 只能装你自己的测试设备
   - `ad-hoc` → 装最多 100 台登记过 UDID 的设备
   - `app-store` → 上传 App Store Connect

5. 下载签好的 ipa，用 **Transporter**（Windows/ Mac 都有）传到 App Store Connect。

---

## App 里的播放器能不能用

iOS 的 WebView（WKWebView）**不支持 MSE**，所以 hls.js 在 iOS 上会自动降级到系统原生 HLS 播放器 —— 这正是我们代码里做的：

```js
if (Hls.isSupported()) {        // Android / 桌面 Chrome → hls.js
  ...
} else if (video.canPlayType("application/vnd.apple.mpegurl")) {
  video.src = apiUrl(media.play);   // iOS → 原生 HLS
}
```

WKWebView 里 `Hls.isSupported()` 返回 `false`，`canPlayType` 返回 `"maybe"`，走第二条分支，用系统播放器。

**要注意的：**

- `playsinline` 已加（否则 iOS 会强制全屏，无法内联播放）
- iOS 原生播放器自带全屏按钮，`F` 快捷键无效
- 后台播放需要 `UIBackgroundModes: audio`，workflow 已自动加
- App 切到后台再回来，视频会暂停，属正常行为

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| Sideloadly 提示 `Provision.cpp:150` | Apple ID 没登录过 iTunes | 打开 iTunes 登录一次再试 |
| 装完打开闪退 | 签名不匹配 / iOS 版本太低 | 确认 iOS 15+，重新签一次 |
| 白屏 | `KS_PUBLIC_BASE` 没配 | 服务端加环境变量重启 |
| 白屏但能进首页 | `server_url` 填错 | 手机 Safari 先访问那个地址 |
| 视频黑屏不播 | 服务端 CORS 或路径问题 | `curl` 测 `/api/media/hls?...` 是否 200 |
| 7 天后打不开 | 免费签名到期 | 重新 Sideloadly，或用 AltStore 自动续签 |
| Codemagic 构建卡在签名 | 没绑 Apple 账号 | 后台 Integrations 里绑 |
| App Store 审核 4.2 被拒 | 判定为网页套壳 | 参见下方说明 |

### 关于 4.2 条款

App Store 审核指南 4.2 条拒绝「仅是对网站的重打包」。我们的做法已经比纯套壳强：

- web 资源打包进 App（不是远程加载）
- 有原生启动屏、状态栏配置
- 播放器、收藏、进度记忆都是 App 本地行为

但审核员仍可能挑刺。审核时在 `App Review Information` 里写清楚：

> KuroStream is a native media client: the UI bundle is embedded in the app,
> playback uses AVPlayer via WKWebView native HLS, and watch history /
> favourites are stored locally. The network layer only fetches catalogue
> metadata and media segments from our own API.

如果还是被拒，补一个 App 独有功能：下载到本地离线观看、后台音频、画质偏好记忆 —— 有一个就算「App 增值」。

---

## 打包前检查清单

- [ ] 站点已上 HTTPS（`bash deploy/ssl.sh 你的域名`）
- [ ] 服务端配了 `KS_PUBLIC_BASE=https://你的域名` 并重启
- [ ] `curl https://你的域名/api/health` 返回 `"public_base":"https://..."`
- [ ] `bundle_id` 没和别人重复
- [ ] iPhone 系统版本 ≥ 15
