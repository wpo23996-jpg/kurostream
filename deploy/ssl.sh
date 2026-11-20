#!/usr/bin/env bash
# 给站点加 HTTPS（Let's Encrypt + nginx）
#   sudo bash deploy/ssl.sh your-domain.com [email]
set -euo pipefail

DOMAIN="${1:?用法: sudo bash deploy/ssl.sh your-domain.com [email]}"
EMAIL="${2:-admin@${DOMAIN}}"

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行" >&2
  exit 1
fi

echo "==> 安装 certbot"
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq certbot python3-certbot-nginx >/dev/null

echo "==> 检查域名解析"
SERVER_IP="$(curl -fsS --max-time 8 https://api.ipify.org || echo '')"
RESOLVED="$(getent hosts "${DOMAIN}" | awk '{print $1; exit}' || echo '')"
if [[ -n "${SERVER_IP}" && -n "${RESOLVED}" && "${RESOLVED}" != "${SERVER_IP}" ]]; then
  echo "⚠️  ${DOMAIN} 解析到 ${RESOLVED}，本机是 ${SERVER_IP}"
  echo "   先把 A 记录指过来，否则证书申请会失败。继续？(y/N)"
  read -r ans
  [[ "${ans}" == "y" ]] || exit 1
fi

echo "==> 申请证书"
certbot --nginx -d "${DOMAIN}" --redirect --agree-tos -m "${EMAIL}" --non-interactive

echo "==> 验证自动续期"
certbot renew --dry-run | tail -3

echo
echo "✅ HTTPS 已启用： https://${DOMAIN}/"
echo "   续期由 certbot.timer 自动处理，检查： systemctl list-timers | grep certbot"
