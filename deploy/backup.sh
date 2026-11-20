#!/usr/bin/env bash
# 备份订单/会员数据库（可加进 crontab 每天跑）
#   sudo bash deploy/backup.sh [备份目录]
set -euo pipefail

APP_DIR="/opt/kurostream"
DB="${APP_DIR}/kurostream.db"
OUT_DIR="${1:-/var/backups/kurostream}"
KEEP=30

[[ -f "${DB}" ]] || { echo "没找到数据库：${DB}"; exit 0; }

mkdir -p "${OUT_DIR}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${OUT_DIR}/kurostream-${STAMP}.db"

# 优先用 sqlite3 的在线备份，没有就退化成文件复制
if command -v sqlite3 >/dev/null 2>&1; then
  sqlite3 "${DB}" ".backup '${DEST}'"
else
  cp "${DB}" "${DEST}"
fi

echo "已备份：${DEST}  ($(du -h "${DEST}" | cut -f1))"

# 只保留最近 N 份
ls -1t "${OUT_DIR}"/kurostream-*.db 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -f
echo "保留最近 ${KEEP} 份，当前 $(ls -1 "${OUT_DIR}"/kurostream-*.db 2>/dev/null | wc -l) 份"
