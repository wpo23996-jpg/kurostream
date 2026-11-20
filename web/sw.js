/* KuroStream service worker
 * 只缓存「应用外壳」，API 与音视频分片一律直连，避免撑爆内存与拿到过期数据。
 */
const VERSION = "v1.6.0";
const CACHE = `ks-${VERSION}`;

const SHELL = [
  "/",
  "/index.html",
  "/style.css?v=1.6.0",
  "/app.js?v=1.6.0",
  "/vendor/hls.min.js",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(SHELL).catch(() => undefined))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;

  // 接口、图片代理、媒体分片：全部直连，不碰缓存
  if (url.pathname.startsWith("/api/")) return;

  // 导航请求：网络优先，断网时回退到缓存的外壳
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).catch(() => caches.match("/index.html").then((r) => r || caches.match("/")))
    );
    return;
  }

  // 静态资源：先用缓存，同时后台更新
  event.respondWith(
    caches.match(req).then((hit) => {
      const network = fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => undefined);
          }
          return res;
        })
        .catch(() => hit);
      return hit || network;
    })
  );
});
