# 零本地环境打包（全免费）

不装 Android Studio、不买 Mac、不装 JDK —— 把代码推到 GitHub，点一下按钮，云端帮你出包。

---

## 方案一：GitHub Actions（推荐，永久免费）

公开仓库的 `ubuntu-latest` 和 `macos-latest` runner 完全免费，每月 2000 分钟（Linux）/ 200 分钟（macOS），一个 App 包用不到 5 分钟。

### 步骤

**1. 注册 GitHub**：<https://github.com>

**2. 建仓库**

- 右上角 `+` → `New repository`
- 名字随便，比如 `kurostream`
- **必须选 Public**（私有仓库的 macOS runner 要扣分钟数）
- 不要勾 README / .gitignore

**3. 上传代码**

网页方式最简单：

- 进入仓库 → `Add file` → `Upload files`
- 把解压出来的 `kurostream/` 里的**所有内容**拖进去（不是拖整个文件夹，是拖里面的东西）
- 注意：`.github` 是隐藏目录，网页上传会丢。改用下面这种方式更稳：

命令行方式（Windows 装个 Git 就行，<https://git-scm.com>）：

```bash
cd kurostream
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/你的用户名/kurostream.git
git push -u origin main
```

**4. 出包**

- 仓库页面 → `Actions` 标签
- 左边选 `Build Android APK` → 右边 `Run workflow`
- 填写：
  - `server_url`：**你的域名**，必须 https，例如 `https://kuro.example.com`
  - `app_name`：应用名，例如 `KuroStream`
- 点绿色 `Run workflow`

**5. 等 3-5 分钟**

跑到绿勾后，点进这次运行，页面底部 **Artifacts** 里下载 `kurostream-android-1.zip`，解压就是 `app-debug.apk`。

传到手机安装（安卓要允许"安装未知来源应用"）。

> 网站必须已经有 HTTPS。没配的话先跑 `bash deploy/ssl.sh 你的域名`。

### 换成正式签名的 release 包

debug 包能装、能用，但上架 Google Play 需要 release 签名。做法：

1. 本地生成 keystore：

```bash
keytool -genkey -v -keystore kuro.jks -keyalg RSA -keysize 2048 -validity 10000 -alias kuro
```

2. 转成 base64：

```bash
base64 -w0 kuro.jks > kuro.jks.b64     # Windows: certutil -encode kuro.jks kuro.b64
```

3. GitHub 仓库 → `Settings` → `Secrets and variables` → `Actions` → 新建 4 个 secret：

| 名字 | 值 |
|---|---|
| `KEYSTORE_BASE64` | kuro.jks.b64 的全部内容 |
| `KEYSTORE_PASSWORD` | 你的 keystore 密码 |
| `KEY_ALIAS` | `kuro` |
| `KEY_PASSWORD` | 你的 key 密码 |

4. 把 `android.yml` 里的 `assembleDebug` 换成 `assembleRelease`，并加上签名步骤（需要的话我可以补一份完整 workflow）。

---

## 方案二：Codemagic（免费 500 分钟/月，含 macOS）

适合**要出 iOS 包但没有 Mac**。

### 步骤

1. 注册：<https://codemagic.io>（用 GitHub 账号登录）
2. 添加应用 → 选你的 GitHub 仓库
3. 构建配置选 **Use codemagic.yaml**（项目根目录已经有这个文件）
4. 进入 `Environment variables` 填：

```
KS_SERVER = https://你的域名.com
```

5. 点 `Start new build` → 选 `Android APK`

结果在构建页面的 `Artifacts` 里直接下载。

### 出 iOS

需要先在 Codemagic 绑定 Apple 账号：

- `Teams` → `Integrations` → `Developer Portal` → 用 Apple ID 登录
- 免费 Apple ID 也能出 **development 签名**（每 7 天要重签，用 AltStore / Sideloadly 装到手机）
- 要上架 App Store，必须付费开发者账号（$99/年）

配好之后选 `iOS IPA` 那个 workflow 跑。

**免费额度**：500 macOS M2 分钟/月，单次构建上限 120 分钟，产物保留 30 天。

---

## 方案三：一键套壳网站（30 秒，最省事但体验差）

这些服务填个网址就给你 APK，**不用代码、不用 GitHub**：

| 服务 | 免费情况 | 说明 |
|---|---|---|
| [Pakr](https://github.com/ZhangShengFan/Pakr) | 开源免费 | 填网址 → 3-5 分钟出可安装 APK，云端签名 |
| [web2apk](https://github.com/Plutonium141/web2apk) | GitHub Action | 自动生成 signed .aab + .apk |
| [Wrapply](https://play.google.com/store/apps/details?id=com.wrapply.app) | 免费试用 | 生成 Flutter 包，在线出 APK/AAB |
| Appy Pie / AppyPie | 免费额度 100 credits | 出包要付费档 |

**它们做的事**：给网址套个 WebView 外壳。

**区别**：我们自己的 `mobile/` 工程是**打包本地资源、只让 API 走网络**，播放器、缓存、全屏行为都可控；一键套壳是**直接加载远程网址**，加载慢、离线就白屏、审核更容易被拒（4.2 条款）。

只想自己用、能用就行 → 用 Pakr，30 秒搞定。
想上架或给客户 → 用方案一 / 二。

---

## 三个方案的对比

| | GitHub Actions | Codemagic | 一键套壳站 |
|---|---|---|---|
| 费用 | 免费 | 免费 500 分钟/月 | 免费/付费档 |
| 安卓 APK | ✅ 3-5 分钟 | ✅ | ✅ 30 秒 |
| iOS IPA | 需要证书 | ✅ 免费账号也能出 dev 包 | ❌ 一般只做安卓 |
| 需要 GitHub | ✅ | ✅ | ❌ |
| 需要 Mac | ❌ | ❌ | ❌ |
| 体验 | 原生壳 | 原生壳 | 网页套壳 |
| 可上架 | ✅ | ✅ | ⚠️ 风险高 |

---

## 常见卡点

| 现象 | 原因 | 处理 |
|---|---|---|
| Actions 里没有 `Build Android APK` | `.github` 目录没上传成功（隐藏目录） | 用 `git push` 而不是网页上传 |
| 构建失败 `SDK not found` | SDK 组件下载超时 | 重跑一次，或删掉 workflow 里的 sdkmanager 步骤 |
| 构建成功但 App 白屏 | `server_url` 填错或没开 HTTPS | 手机浏览器先打开那个地址确认能访问 |
| App 里能浏览但视频不播 | 服务端没配 `KS_PUBLIC_BASE` | `KS_PUBLIC_BASE=https://域名` 写进 `/etc/kurostream/env` 后重启 |
| iOS 构建卡在签名 | 没绑 Apple 账号 | Codemagic 后台 Integrations 里绑 |
| 装 APK 提示"应用未安装" | 之前装过同包名不同签名版本 | 先卸载旧的 |
| 免费 Apple ID 装的 App 7 天后打不开 | 开发签名的固有期限 | 用 AltStore 自动续签，或买 $99 开发者账号 |
