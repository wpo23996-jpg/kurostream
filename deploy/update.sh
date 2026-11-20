#!/usr/bin/env bash
# 升级代码（保留配置与数据库）
#   sudo bash deploy/update.sh /root/kurostream-v1.5.0/kurostream
set -euo pipefail

NEW_DIR="${1:?用法: sudo bash deploy/update.sh <新版本目录>}"
APP_DIR="/opt/kurostream"
CONF_DIR="/etc/kurostream"
SERVICE="kurostream.service"

[[ $EUID -eq 0 ]] || { echo "请用 root 运行" >&2; exit 1; }
[[ -f "${NEW_DIR}/run.py" ]] || { echo "目录不对：${NEW_DIR}/run.py 不存在" >&2; exit 1; }

echo "==> 1/5 备份数据库"
if [[ -f "${APP_DIR}/kurostream.db" ]]; then
  mkdir -p /var/backups/kurostream
  cp "${APP_DIR}/kurostream.db" "/var/backups/kurostream/kurostream-$(date +%Y%m%d-%H%M%S).db"
  echo "   已备份到 /var/backups/kurostream/"
fi

echo "==> 2/5 覆盖代码（不动 venv / db / env）"
rsync -a --delete \
  --exclude 'venv' --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm' \
  --exclude '__pycache__' --exclude '*.pyc' \
  "${NEW_DIR}/" "${APP_DIR}/"

echo "==> 3/5 更新依赖"
"${APP_DIR}/venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt"

echo "==> 4/5 权限"
chown -R kurostream:kurostream "${APP_DIR}"

echo "==> 5/5 重启并检查"
systemctl restart "${SERVICE}"
PORT="$(grep -E '^KS_PORT=' "${CONF_DIR}/env" 2>/dev/null | cut -d= -f2 | tr -d '[:space:]')"
PORT="${PORT:-8000}"
for i in $(seq 1 15); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then
    echo "✅ 升级完成，服务正常"
    exit 0
  fi
  sleep 2
done

echo "⚠️  升级后健康检查失败：" >&2
journalctl -u "${SERVICE}" -n 40 --no-pager >&2
exit 1
