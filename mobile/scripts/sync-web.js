#!/usr/bin/env node
/**
 * 把 ../web 复制到 ./www，并把 index.html 里的 __KS_CONFIG__ 注入为你的服务器地址。
 * 必须先设置环境变量：
 *   KS_SERVER=https://你的域名.com   （必须 https）
 */
const fs = require("fs");
const path = require("path");

const server = (process.env.KS_SERVER || "").trim().replace(/\/+$/, "");
if (!server) {
  console.error("\n✗ 请先设置服务器地址：");
  console.error("   Windows:  set KS_SERVER=https://your-domain.com && npm run sync:web");
  console.error("   macOS/Linux:  KS_SERVER=https://your-domain.com npm run sync:web\n");
  process.exit(1);
}
if (!/^https?:\/\//.test(server)) {
  console.error("✗ KS_SERVER 必须以 http:// 或 https:// 开头");
  process.exit(1);
}

const here = path.resolve(__dirname, "..");
const src = path.resolve(here, "../web");
const dst = path.resolve(here, "www");

if (!fs.existsSync(src)) {
  console.error(`✗ 找不到 web 目录：${src}`);
  process.exit(1);
}

fs.rmSync(dst, { recursive: true, force: true });
fs.cpSync(src, dst, { recursive: true });

const indexFile = path.join(dst, "index.html");
let html = fs.readFileSync(indexFile, "utf8");

const marker = /window\.__KS_CONFIG__\s*=\s*window\.__KS_CONFIG__\s*\|\|\s*\{\s*apiBase:\s*""\s*\};/;
const replacement = `window.__KS_CONFIG__ = { apiBase: ${JSON.stringify(server)} };`;

if (!marker.test(html)) {
  console.error("✗ index.html 里没找到 __KS_CONFIG__ 标记，请确认用的是 v1.6.0+ 的 web 目录");
  process.exit(1);
}
html = html.replace(marker, replacement);
fs.writeFileSync(indexFile, html, "utf8");

console.log(`✓ www 已生成`);
console.log(`  源目录 : ${src}`);
console.log(`  目标   : ${dst}`);
console.log(`  API    : ${server}`);
console.log(`\n下一步：`);
console.log(`  Android:  npx cap add android && npx cap sync android && npx cap open android`);
console.log(`  iOS    :  npx cap add ios     && npx cap sync ios     && npx cap open ios`);
