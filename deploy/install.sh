#!/usr/bin/env bash
# KuroStream 一键安装（Debian 11+ / Ubuntu 22.04+）
#   sudo bash deploy/install.sh                  # 用 IP 访问
#   sudo bash deploy/install.sh your-domain.com  # 绑定域名
set -euo pipefail

APP_NAME="kurostream"
APP_DIR="/opt/${APP_NAME}"
CONF_DIR="/etc/${APP_NAME}"
SERVICE="${APP_NAME}.service"
DOMAIN="${1:-_}"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

red()  { printf "\033[31m%s\033[0m\n" "$*"; }
green(){ printf "\033[32m%s\033[0m\n" "$*"; }
note() { printf "\033[36m%s\033[0m\n" "$*"; }

[[ $EUID -eq 0 ]] || { red "请用 root 运行：sudo bash deploy/install.sh [domain]"; exit 1; }

# ---------------------------------------------------------------- 0. 环境检查
echo "==> 0/7 环境检查"
command -v python3 >/dev/null || { red "缺少 python3"; exit 1; }

PY_OK=0
python3 - <<'EOF' >/dev/null 2>&1 || PY_OK=1
import sys
sys.exit(0 if sys.version_info >= (3, 10) else 1)
EOF
if [[ $PY_OK -ne 0 ]]; then
  red "当前 Python 版本过低：$(python3 -V 2>&1)"
  red "KuroStream 需要 Python 3.10+。"
  echo "  Ubuntu 20.04 先执行:"
  echo "    apt-get install -y software-properties-common"
  echo "    add-apt-repository -y ppa:deadsnakes/ppa"
  echo "    apt-get update && apt-get install -y python3.11 python3.11-venv"
  echo "    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1"
  exit 1
fi
green "Python $(python3 -V 2>&1 | awk '{print $2}') OK"

ARCH="$(uname -m)"
note "架构：${ARCH}（curl_cffi 会自动下载对应 wheel）"

# ------------------------------------------------------------------- 1. 依赖
echo "==> 1/7 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx curl ca-certificates rsync >/dev/null

# ------------------------------------------------------------------- 2. 用户
echo "==> 2/7 创建运行用户"
id -u "${APP_NAME}" >/dev/null 2>&1 || \
  useradd --system --home "${APP_DIR}" --shell /usr/sbin/nologin "${APP_NAME}"

# ------------------------------------------------------------------- 3. 代码
echo "==> 3/7 部署代码到 ${APP_DIR}"
mkdir -p "${APP_DIR}" "${CONF_DIR}"
if [[ "${SRC_DIR}" != "${APP_DIR}" ]]; then
  if command -v rsync >/dev/null; then
    rsync -a --delete \
      --exclude '__pycache__' --exclude '*.pyc' --exclude '.git' \
      --exclude 'venv' --exclude '*.db' --exclude '*.db-wal' --exclude '*.db-shm' \
      "${SRC_DIR}/" "${APP_DIR}/"
  else
    find "${APP_DIR}" -mindepth 1 -delete 2>/dev/null || true
    cp -a "${SRC_DIR}/." "${APP_DIR}/"
  fi
fi
find "${APP_DIR}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
chmod +x "${APP_DIR}/deploy/"*.sh 2>/dev/null || true

# ------------------------------------------------------------------- 4. venv
echo "==> 4/7 创建虚拟环境并安装依赖（约 1-2 分钟）"
python3 -m venv "${APP_DIR}/venv"
"${APP_DIR}/venv/bin/pip" install -q --upgrade pip wheel
"${APP_DIR}/venv/bin/pip" install -q -r "${APP_DIR}/requirements.txt"

# -------------------------------------------------------------------- 5. env
echo "==> 5/7 写入环境配置 ${CONF_DIR}/env"
NEW_TOKEN=""
if [[ ! -f "${CONF_DIR}/env" ]]; then
  NEW_TOKEN="$(head -c 64 /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 32)"
  cat > "${CONF_DIR}/env" <<EOF
# 监听：nginx 反代到 127.0.0.1，不要改成 0.0.0.0（会被直接扫端口）
KS_HOST=127.0.0.1
KS_PORT=8000
KS_WORKERS=1

# 品牌
KS_SITE_NAME=KuroStream
KS_TAGLINE=高清片库 · 极速播放

# 抓取与缓存
KS_MIN_INTERVAL=0.35
KS_TIMEOUT=30
KS_RETRIES=3
KS_CACHE_TTL=300
KS_LOG_LEVEL=info
KS_PROXY=

# 对外绝对地址（打包 App 时填写 https://你的域名）
KS_PUBLIC_BASE=

# 订单库（相对 /opt/kurostream）
KS_DB=kurostream.db

# 管理令牌：确认收款、查看统计用
KS_ADMIN_TOKEN=${NEW_TOKEN}

# 收款账号：填哪个渠道，定价页就显示哪个
KS_PAY_ALIPAY=
KS_PAY_USDT=
KS_PAY_MANUAL=
KS_PAY_NOTE=付款时务必备注订单号，否则无法自动到账确认
EOF
  chmod 600 "${CONF_DIR}/env"
  chown root:root "${CONF_DIR}/env"
else
  note "已存在 ${CONF_DIR}/env，保留原配置"
fi

# ---------------------------------------------------------------- 6. systemd
echo "==> 6/7 配置 systemd"
install -m 0644 "${APP_DIR}/deploy/${SERVICE}" "/etc/systemd/system/${SERVICE}"
chown -R "${APP_NAME}:${APP_NAME}" "${APP_DIR}"
systemctl daemon-reload
systemctl enable --now "${SERVICE}" >/dev/null

# ------------------------------------------------------------------- 7. nginx
echo "==> 7/7 配置 nginx"
sed "s/__DOMAIN__/${DOMAIN}/" "${APP_DIR}/deploy/nginx.conf" > "/etc/nginx/sites-available/${APP_NAME}"
ln -sf "/etc/nginx/sites-available/${APP_NAME}" "/etc/nginx/sites-enabled/${APP_NAME}"
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx

command -v ufw >/dev/null 2>&1 && { ufw allow 80/tcp >/dev/null 2>&1 || true; ufw allow 443/tcp >/dev/null 2>&1 || true; }

# -------------------------------------------------------------------- 健康检查
PORT="$(grep -E '^KS_PORT=' "${CONF_DIR}/env" | cut -d= -f2 | tr -d '[:space:]')"
PORT="${PORT:-8000}"
OK=0
for i in $(seq 1 20); do
  if curl -fsS "http://127.0.0.1:${PORT}/api/health" >/dev/null 2>&1; then OK=1; break; fi
  sleep 2
done

echo
if [[ $OK -eq 1 ]]; then
  green "✅ 安装完成"
  echo "   站点：   http://${DOMAIN/_/你的服务器IP}/"
  echo "   服务：   systemctl status ${APP_NAME}"
  echo "   日志：   journalctl -u ${APP_NAME} -f"
  echo "   配置：   ${CONF_DIR}/env  （改完 systemctl restart ${APP_NAME}）"
  echo "   数据库： ${APP_DIR}/kurostream.db"
  TOKEN="$(grep -E '^KS_ADMIN_TOKEN=' "${CONF_DIR}/env" | cut -d= -f2-)"
  [[ -n "${TOKEN}" ]] && echo "   后台令牌：${TOKEN}"
  echo
  note "接下来 3 步："
  echo "   1) 编辑 ${CONF_DIR}/env，填 KS_PAY_ALIPAY / KS_PAY_USDT"
  echo "   2) systemctl restart ${APP_NAME}"
  echo "   3) 绑域名 + HTTPS：bash ${APP_DIR}/deploy/ssl.sh your-domain.com"
  echo
  note "云服务器记得在【安全组】放行 80 / 443 端口，否则外网打不开。"
else
  red "⚠️  服务已安装但健康检查失败"
  echo "   journalctl -u ${APP_NAME} -n 60 --no-pager" >&2
  echo "   ${APP_DIR}/venv/bin/python ${APP_DIR}/run.py   # 前台跑一遍看报错" >&2
  exit 1
fi
