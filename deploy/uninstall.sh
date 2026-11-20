#!/usr/bin/env bash
# 卸载（默认保留数据库与配置）
#   sudo bash deploy/uninstall.sh          # 只停服务、删代码，保留 /etc/kurostream 与数据库
#   sudo bash deploy/uninstall.sh --purge  # 连配置和数据库一起删
set -euo pipefail

PURGE=0
[[ "${1:-}" == "--purge" ]] && PURGE=1

[[ $EUID -eq 0 ]] || { echo "请用 root 运行" >&2; exit 1; }

echo "==> 停止服务"
systemctl disable --now kurostream.service 2>/dev/null || true
rm -f /etc/systemd/system/kurostream.service
systemctl daemon-reload

echo "==> 移除 nginx 配置"
rm -f /etc/nginx/sites-enabled/kurostream /etc/nginx/sites-available/kurostream
nginx -t >/dev/null 2>&1 && systemctl reload nginx || true

if [[ $PURGE -eq 1 ]]; then
  echo "==> 全量删除（含数据库）"
  rm -rf /opt/kurostream /etc/kurostream /var/backups/kurostream
  id -u kurostream >/dev/null 2>&1 && userdel kurostream 2>/dev/null || true
  echo "✅ 已彻底卸载"
else
  echo "==> 备份数据后删除代码"
  if [[ -f /opt/kurostream/kurostream.db ]]; then
    mkdir -p /var/backups/kurostream
    cp /opt/kurostream/kurostream.db "/var/backups/kurostream/final-$(date +%Y%m%d-%H%M%S).db"
    echo "   数据库已备份到 /var/backups/kurostream/"
  fi
  rm -rf /opt/kurostream
  echo "✅ 已卸载代码；配置保留在 /etc/kurostream"
  echo "   彻底删除： sudo bash deploy/uninstall.sh --purge"
fi
