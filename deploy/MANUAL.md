# 手动部署（逐步命令）

适用于 Ubuntu 22.04 / Debian 12，1 核 2G 起步。全程复制粘贴即可。

> 一键脚本也行：`sudo bash deploy/install.sh your-domain.com`
> 这份文档是逐步版，出问题时更容易定位。

---

## 0. 准备

```bash
# 更新系统
apt-get update && apt-get upgrade -y

# 检查 Python 版本，必须是 3.10+
python3 -V
```

如果低于 3.10（例如 Ubuntu 20.04 是 3.8）：

```bash
apt-get install -y software-properties-common
add-apt-repository -y ppa:deadsnakes/ppa
apt-get update
apt-get install -y python3.11 python3.11-venv
update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
python3 -V   # 确认 3.11
```

---

## 1. 上传代码

本地打包好的 `kurostream-v1.5.0.zip` 上传到服务器：

```bash
# 在你自己的电脑上执行（不是服务器）
scp kurostream-v1.5.0.zip root@你的服务器IP:/root/
```

服务器上解压：

```bash
apt-get install -y unzip
cd /root
unzip -q kurostream-v1.5.0.zip
ls kurostream/          # 应该看到 app/ web/ deploy/ run.py
```

---

## 2. 装系统依赖

```bash
apt-get install -y python3 python3-venv python3-pip nginx curl rsync
```

---

## 3. 建运行用户

```bash
id -u kurostream || useradd --system --home /opt/kurostream --shell /usr/sbin/nologin kurostream
```

---

## 4. 部署代码

```bash
mkdir -p /opt/kurostream /etc/kurostream
rsync -a --delete /root/kurostream/ /opt/kurostream/
chmod +x /opt/kurostream/deploy/*.sh
```

---

## 5. 建虚拟环境装依赖

```bash
python3 -m venv /opt/kurostream/venv
/opt/kurostream/venv/bin/pip install --upgrade pip wheel
/opt/kurostream/venv/bin/pip install -r /opt/kurostream/requirements.txt
```

> 装 `curl_cffi` 时会下载对应架构的预编译包，通常 30 秒内完成。
> 如果卡住，先确认服务器能访问 pypi.org。

---

## 6. 写配置

```bash
# 生成一个管理令牌
TOKEN=$(head -c 64 /dev/urandom | tr -dc 'a-zA-Z0-9' | head -c 32)
echo "你的后台令牌：$TOKEN"   # 记下来

cat > /etc/kurostream/env <<EOF
KS_HOST=127.0.0.1
KS_PORT=8000
KS_WORKERS=1
KS_SITE_NAME=KuroStream
KS_TAGLINE=高清片库 · 极速播放
KS_MIN_INTERVAL=0.35
KS_TIMEOUT=30
KS_RETRIES=3
KS_CACHE_TTL=300
KS_LOG_LEVEL=info
KS_PROXY=
KS_DB=kurostream.db
KS_ADMIN_TOKEN=$TOKEN
KS_PAY_ALIPAY=
KS_PAY_USDT=
KS_PAY_MANUAL=
KS_PAY_NOTE=付款时务必备注订单号
EOF

chmod 600 /etc/kurostream/env
```

---

## 7. 先手动跑一次

**这一步很重要**，确认代码能起来，再交给 systemd。

```bash
cd /opt/kurostream
set -a; . /etc/kurostream/env; set +a
./venv/bin/python run.py
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就算成功。
另开一个终端验证：

```bash
curl http://127.0.0.1:8000/api/health
# {"ok":true,"providers":8}

curl "http://127.0.0.1:8000/api/browse?provider=jp-hd&limit=3"
```

确认无误后 `Ctrl+C` 停掉。

---

## 8. 配置 systemd

```bash
cp /opt/kurostream/deploy/kurostream.service /etc/systemd/system/
chown -R kurostream:kurostream /opt/kurostream
systemctl daemon-reload
systemctl enable --now kurostream
systemctl status kurostream --no-pager
```

日志：

```bash
journalctl -u kurostream -f
```

---

## 9. 配置 nginx

```bash
sed 's/__DOMAIN__/_/' /opt/kurostream/deploy/nginx.conf > /etc/nginx/sites-available/kurostream
ln -sf /etc/nginx/sites-available/kurostream /etc/nginx/sites-enabled/kurostream
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

现在浏览器打开 `http://你的服务器IP/` 应该能看到首页。

> **打不开先查安全组**：阿里云/腾讯云/AWS 的防火墙在控制台，不在服务器上。
> `ufw status` 只是本机防火墙，云厂商安全组还要单独放行 80/443。

---

## 10. 绑域名 + HTTPS

域名 A 记录指向服务器 IP，然后：

```bash
apt-get install -y certbot python3-certbot-nginx
certbot --nginx -d your-domain.com --redirect --agree-tos -m admin@your-domain.com --non-interactive
```

成功后访问 `https://your-domain.com/`。

---

## 11. 填收款账号

```bash
nano /etc/kurostream/env
```

把这三个填上（填哪个显示哪个）：

```bash
KS_PAY_ALIPAY=https://qr.alipay.com/xxxx       # 支付宝收款码链接
KS_PAY_USDT=Txxxxxxxxxxxxxxxxxxxxxxxxxxxx      # USDT-TRC20 地址
KS_PAY_MANUAL=TG: @yourname                    # 或者人工客服联系方式
```

重启：

```bash
systemctl restart kurostream
```

打开站点点「会员」，能看到订单页和收款信息。

---

## 12. 收款确认

用户付款后点「我已完成支付」，订单进待确认队列。你确认到账后执行：

```bash
TOKEN=$(grep '^KS_ADMIN_TOKEN=' /etc/kurostream/env | cut -d= -f2)

# 看所有待确认订单
curl -s "http://127.0.0.1:8000/api/admin/stats" -H "X-Admin-Token: $TOKEN"

# 确认某一单（订单号在前端订单页能看到，或查数据库）
curl -X POST "http://127.0.0.1:8000/api/admin/order/KS26112003323244184/confirm" \
     -H "X-Admin-Token: $TOKEN"
```

会员立刻生效，用户前端 4 秒内自动解锁。

查数据库里的待确认订单：

```bash
apt-get install -y sqlite3
sqlite3 /opt/kurostream/kurostream.db \
  "SELECT order_no, tier, amount, channel, datetime(created_at,'unixepoch','localtime') FROM orders WHERE status='claimed' ORDER BY created_at DESC;"
```

---

## 13. 日常维护

```bash
# 备份订单库（建议加进 crontab）
bash /opt/kurostream/deploy/backup.sh

# 每天凌晨 3 点自动备份
echo "0 3 * * * root bash /opt/kurostream/deploy/backup.sh >/dev/null 2>&1" > /etc/cron.d/kurostream-backup

# 升级到新版本
sudo bash /opt/kurostream/deploy/update.sh /root/kurostream-vX.Y.Z/kurostream

# 卸载（保留数据）
sudo bash /opt/kurostream/deploy/uninstall.sh
```

---

## 排错速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `ModuleNotFoundError: curl_cffi` | venv 没装依赖 | `/opt/kurostream/venv/bin/pip install -r /opt/kurostream/requirements.txt` |
| `TypeError: unsupported operand type(s) ... \|` | Python < 3.10 | 换 3.11，见第 0 步 |
| 502 Bad Gateway | 服务没起来 | `journalctl -u kurostream -n 50` |
| 页面能开但搜不出东西 | 服务器出网被限 | `curl -I https://missav.ws` 测连通 |
| 图片全空白 | 出网慢或被墙 | 在 `/etc/kurostream/env` 配 `KS_PROXY=http://...` |
| 域名打不开、IP 能开 | nginx server_name 不匹配 | 重跑第 9 步，`__DOMAIN__` 换成真实域名 |
| 外网完全连不上 | 云安全组没放行 | 控制台开 80/443 |
| 订单确认 503 | 没设 `KS_ADMIN_TOKEN` | 在 env 里补上并重启 |
| 多 worker 下会员状态不一致 | 各自独立缓存 | 保持 `KS_WORKERS=1`，或统一读库（已用 WAL） |
