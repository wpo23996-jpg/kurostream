# iOS / Android 构建说明

> **不想装任何环境？**
> - iOS → **[IOS.md](IOS.md)**（GitHub Actions 出未签名 ipa + Sideloadly 自签，零成本）
> - 安卓 → **[BUILD-CLOUD.md](BUILD-CLOUD.md)**（GitHub Actions 一键出 APK）

三种交付方式，按你的需要选：

| 方式 | 成本 | 能上架 | 适合 |
|---|---|---|---|
| **PWA** | 0 | ✗ | 立刻可用，手机浏览器「添加到主屏幕」 |
| **Android APK** | 1 小时 | ✓（Google Play 或直接给安装包） | 安卓用户 |
| **iOS IPA** | 需要 Mac | ✓（App Store）或自签 | 苹果用户 |

---

## 一、PWA（服务器已自带，无需构建）

`web/` 目录里已经有 `manifest.webmanifest`、`sw.js`、全套图标。部署到 HTTPS 域名后：

- **Android Chrome**：打开站点 → 菜单 → 「安装应用」/「添加到主屏幕」
- **iOS Safari**：打开站点 → 分享 → 「添加到主屏幕」

添加后是全屏无地址栏，和原生 App 观感一致。收藏、播放进度都存在本机。

> 必须是 **HTTPS**，iOS 的 PWA 不接受 http。
> `bash deploy/ssl.sh 你的域名` 一条命令搞定证书。

---

## 二、Android（Windows / Mac / Linux 都能做）

### 环境

1. **JDK 17**：<https://adoptium.net>
2. **Android Studio**：<https://developer.android.com/studio>
3. **Node.js 18+**

### 步骤

```bash
cd kurostream/mobile

# 装依赖
npm install

# 生成 www 并注入你的服务器地址（必须是 https）
# Windows:
set KS_SERVER=https://your-domain.com
npm run sync:web

# macOS / Linux:
KS_SERVER=https://your-domain.com npm run sync:web

# 生成安卓工程（只需一次）
npx cap add android

# 同步资源
npx cap sync android

# 打开 Android Studio
npx cap open android
```

在 Android Studio 里：

- `Build → Generate Signed Bundle / APK`
- 选 **APK**（自己分发）或 **AAB**（上架 Google Play）
- 创建签名密钥，记好密码（丢了不能更新应用）
- 出品

**命令行直接出 debug 包**：

```bash
cd android
./gradlew assembleDebug          # 产物：app/build/outputs/apk/debug/app-debug.apk
```

### 出包前检查

- `mobile/capacitor.config.json` 里的 `appId` 改成你自己的（默认 `com.kurostream.app`），**上架后不能再改**
- 服务器必须 HTTPS，否则安卓 9+ 默认禁止明文请求
- `android/app/src/main/AndroidManifest.xml` 已经有 `INTERNET` 权限，不用动

---

## 三、iOS（必须有 Mac + Xcode）

### 环境

1. **macOS 13+**
2. **Xcode 15+**（App Store 下载）
3. **CocoaPods**：`sudo gem install cocoapods`
4. **Node.js 18+**

### 步骤

```bash
cd kurostream/mobile
npm install

KS_SERVER=https://your-domain.com npm run sync:web

npx cap add ios
npx cap sync ios
npx cap open ios
```

在 Xcode 里：

1. 选中 `App` target → **Signing & Capabilities** → 选你的 Apple Developer 账号
2. `Bundle Identifier` 改成你的（不能和别人重复）
3. 真机调试：连上 iPhone，选设备，`Cmd+R`
4. 出包：`Product → Archive` → `Distribute App` → App Store Connect

**上架注意**：App Store 审核对「纯网页套壳」有 4.2 条款风险。
降低风险的做法：App 内已经有原生播放器、本地收藏、离线缓存，且不是加载远程 URL（我们打包本地资源，只让 API 走网络），通常能过。如果被拒，补一个「仅 App 可用」的功能（比如下载列表）。

### 没 Mac 怎么办

用云端 macOS 构建：

- **Codemagic**：免费额度每月 500 分钟，绑定 GitHub 仓库即可出 IPA
- **GitHub Actions**：`macos-latest` runner，配 fastlane 出包

两者都需要 Apple Developer 账号（个人 $99/年）才能上架或自签。

---

## 四、改服务器地址

App 里的 API 地址在构建时写死进 `www/index.html`：

```html
<script>window.__KS_CONFIG__ = { apiBase: "https://your-domain.com" };</script>
```

换域名后重新执行 `KS_SERVER=https://新域名 npm run sync:web && npx cap sync`，再出包。

服务端对应也要配（让播放地址变成绝对路径，否则壳里取不到分片）：

```bash
# /etc/kurostream/env
KS_PUBLIC_BASE=https://your-domain.com
systemctl restart kurostream
```

验证：

```bash
curl https://your-domain.com/api/health
# {"ok":true,"providers":8,"version":"1.6.0","public_base":"https://your-domain.com"}
```

`public_base` 有值就说明配置生效了。

---

## 五、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| App 打开白屏 | `www` 没生成或为空 | 重跑 `npm run sync:web`，检查 `mobile/www/index.html` 存在 |
| 能进首页但列表空白 | `KS_PUBLIC_BASE` 没配 | 服务端加环境变量并重启 |
| 视频转圈不播 | 壳内跨域被拦 | 服务端 CORS 已开 `*`，确认 nginx 没覆盖 `Access-Control-Allow-Origin` |
| iOS 视频没声音/不自动播 | WebView 自动播放策略 | 我们的播放器是用户点击触发，正常；静音自动播放需原生配置 |
| 安卓报 `net::ERR_CLEARTEXT_NOT_PERMITTED` | 用了 http | 换 https |
| 上架被拒 4.2 | 被判定为套壳 | 补充原生功能，或在审核说明里解释 |
| 真机调试连不上本地 | 手机和电脑不同网段 | 用电脑局域网 IP，且 `KS_HOST=0.0.0.0` |
