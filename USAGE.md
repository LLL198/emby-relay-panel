# emby-relay-panel 部署手册

本文给“拿到 Git 仓库、自己部署一套面板”的管理员使用。所有域名、IP、密码和 Token 都是示例，必须替换成自己的值。

## 1. 准备资源

### 1.1 主控机

- Debian/Ubuntu 22.04+、Debian 13，或 Alpine 3.20+。
- 公网 IP，安全组放行 TCP 80 和 443。
- 一个主站域名，例如 `sh.example.com`，DNS A/AAAA 记录指向主控机。
- 建议至少 1 GB 内存；线路和播放器流量主要消耗节点带宽，不会全部经过主控机。

### 1.2 Cloudflare

节点域名由 `AUTO_NODE_ZONE` 下面的子域组成，例如 Zone 为 `example.com` 时，程序会创建 `n-xxx.example.com` 和 `*.n-xxx.example.com`。

创建 API Token 时只给：

- Zone - Zone - Read
- Zone - DNS - Edit
- Zone Resources 限制为实际的 `example.com`

`AUTO_NODE_ZONE` 填 Zone 名称（`example.com`），不要填主站完整域名（`sh.example.com`）。

### 1.3 节点

每台节点需要：

- 可从主控机连到的 SSH 地址和端口；自动部署阶段需要 root SSH。
- VPS：填写节点公网 HTTPS 端口和节点内部监听端口，通常都是 `443`。
- NAT：填写服务商映射的公网端口和内部端口。例如 `30000 -> 80`，公网端口填 `30000`，内部端口填 `80`。
- 如果节点已经安装并监听 Nginx，程序会读取它实际的 HTTPS/HTTP 监听端口；检测到已有 Nginx 后，表单中的内部端口会被忽略。公网端口仍必须填写服务商映射端口。

## 2. 安装主控机依赖

以下命令在主控机执行。

### Debian/Ubuntu

```bash
apt-get update
apt-get install -y git python3 python3-pip python3-venv nginx openssl curl openssh-client sshpass ca-certificates
```

### Alpine

```bash
apk add --no-cache git python3 py3-pip nginx openssl curl openssh-client sshpass ca-certificates
```

若看到 `apt ... lock`，说明另一项系统更新正在运行，先等待它结束再执行安装。若看到 `openssl: not found`，必须在**报错的那台机器**安装 `openssl`。

## 3. 下载项目和 Python 依赖

```bash
install -d -m 0755 /opt
git clone https://github.com/LLL198/emby-relay-panel.git /opt/uniproxy
cd /opt/uniproxy
python3 -m venv /opt/uniproxy/.venv
/opt/uniproxy/.venv/bin/pip install --upgrade pip
/opt/uniproxy/.venv/bin/pip install aiohttp cryptography
```

如果系统禁止创建 venv，可使用系统 Python 安装 `aiohttp` 和 `cryptography`，但生产环境更推荐 venv。确认代码没有明显语法错误：

```bash
/opt/uniproxy/.venv/bin/python -m py_compile panel.py uniproxy.py origin_security.py
```

## 4. 安装并检查 acme.sh

主控机需要用 `acme.sh` 为新节点申请证书。安装后检查可执行文件是否存在：

```bash
curl https://get.acme.sh | sh
/root/.acme.sh/acme.sh --version
```

如果路径不存在，先确认安装脚本执行用户和 `ACME_HOME`；不要启动面板后才处理。`acme.sh` 运行时报 `openssl: not found` 时，在报错机器安装 `openssl` 并重新检查。

## 5. 创建秘密环境文件

生成随机值（每次输出都不同）：

```bash
python3 - <<'PY'
from cryptography.fernet import Fernet
import secrets
print('AGENT_TOKEN=' + secrets.token_urlsafe(32))
print('INVITE_CODE_ENCRYPTION_KEY=' + Fernet.generate_key().decode())
print('NODE_CREDENTIAL_ENCRYPTION_KEY=' + Fernet.generate_key().decode())
print('AUTH_THROTTLE_SECRET=' + secrets.token_urlsafe(32))
PY
```

创建 `/root/.secrets/uniproxy-panel.env`（不要提交 Git）：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=换成随机长密码
AGENT_TOKEN=上一步生成的值
INVITE_CODE_ENCRYPTION_KEY=上一步生成的Fernet值
NODE_CREDENTIAL_ENCRYPTION_KEY=上一步生成的Fernet值
AUTH_THROTTLE_SECRET=上一步生成的值

PANEL_DB_PATH=/var/lib/uniproxy/panel.db
TRAFFIC_LOG_PATH=/var/log/uniproxy-traffic.log
PROXY_DOMAIN_SUFFIX=sh.example.com
AUTO_NODE_ZONE=example.com
PANEL_PUBLIC_ORIGIN=https://sh.example.com
PUBLIC_HTTPS_PORT=443
PUBLIC_HTTP_PORT=80
TLS_CERT_FILE=/etc/letsencrypt/live/sh.example.com/fullchain.pem
TLS_KEY_FILE=/etc/letsencrypt/live/sh.example.com/privkey.pem
```

创建目录并限制权限：

```bash
install -d -m 0700 /root/.secrets /var/lib/uniproxy
chown root:root /root/.secrets/uniproxy-panel.env
chmod 0600 /root/.secrets/uniproxy-panel.env
```

`ADMIN_PASSWORD` 不能为空。两个 Fernet 密钥不能互换，也不能使用管理员密码代替。丢失密钥可能导致已有邀请码或节点凭据无法解密。

## 6. 配置 Cloudflare Token 文件

在主控机创建 `/opt/uniproxy/acme-account.conf`，文件只保留下面一行：

```bash
SAVED_CF_Token='你的Cloudflare API Token'
```

```bash
chown root:root /opt/uniproxy/acme-account.conf
chmod 0600 /opt/uniproxy/acme-account.conf
```

不要把 Token 写进 systemd、Nginx 配置、截图或 Git。程序只从主控机读取它，节点部署流程不会把该 Token 复制到节点。Token 失效或权限不含 DNS Edit 时，添加节点会提示 Cloudflare DNS 错误。

## 7. 准备主站 TLS 和 Nginx

主站证书需要在启动服务前准备好。例如证书文件应存在：

```bash
test -s /etc/letsencrypt/live/sh.example.com/fullchain.pem
test -s /etc/letsencrypt/live/sh.example.com/privkey.pem
```

复制并修改服务模板：

```bash
cp /opt/uniproxy/uniproxy.service /etc/systemd/system/uniproxy.service
```

检查模板里的 `PROXY_DOMAIN_SUFFIX`、`AUTO_NODE_ZONE`、`PANEL_PUBLIC_ORIGIN`、`TLS_CERT_FILE` 和 `TLS_KEY_FILE` 与自己的域名一致。保持面板只监听本机：

```dotenv
LISTEN_HOST=127.0.0.1
LISTEN_PORT=8787
```

本手册使用上面创建的虚拟环境，因此把服务的启动行改为：

```bash
sed -i 's#^ExecStart=.*#ExecStart=/opt/uniproxy/.venv/bin/python /opt/uniproxy/uniproxy.py#' /etc/systemd/system/uniproxy.service
```

如果你不使用虚拟环境，就把 `aiohttp` 和 `cryptography` 安装到 `/usr/bin/python3` 对应的系统环境，并保留原来的 `ExecStart`。

不要把 8787 直接暴露到公网。

### 使用示例 Nginx 配置

`deploy/sh.996878.xyz.nginx` 是 `sh.996878.xyz` 的示例。复制后至少修改：

- `server_name`
- 主站证书和私钥路径
- 上游 `127.0.0.1:8787`（如果你修改了监听端口则同步修改）

同时加载 `deploy/00-uniproxy-security.conf` 中的限速区。`deploy/01-cloudflare-realip.conf` 只有在主站确实经过 Cloudflare 时才启用。

Debian/Ubuntu 常见安装方式（确认 `/etc/nginx/nginx.conf` 包含 `conf.d/*.conf`）：

```bash
install -m 0644 /opt/uniproxy/deploy/00-uniproxy-security.conf /etc/nginx/conf.d/00-uniproxy-security.conf
cp /opt/uniproxy/deploy/sh.996878.xyz.nginx /etc/nginx/conf.d/sh.example.com.nginx
```

Alpine 通常使用 `/etc/nginx/http.d/`；把两个文件放到 Nginx 主配置实际 `include` 的目录即可。不要同时启用旧的 `sh.lplww.xyz.redirect.nginx` 示例。

示例配置默认启用了 Cloudflare Origin Pull：

```nginx
ssl_client_certificate /etc/nginx/certs/cloudflare-origin-pull-ca.pem;
ssl_verify_client on;
```

如果你没有安装 Cloudflare Origin Pull CA，就删除这两行；否则 `nginx -t` 会因证书文件不存在而失败。修改后执行：

```bash
nginx -t
systemctl reload nginx
```

## 8. 启动和首次登录

```bash
systemctl daemon-reload
systemctl enable --now uniproxy
systemctl status uniproxy --no-pager
journalctl -u uniproxy -n 100 --no-pager
```

第一次成功启动时，程序会用 `ADMIN_USERNAME`/`ADMIN_PASSWORD` 创建管理员账号。之后管理员和普通用户共用 `/login`；管理员登录到用户首页后，会看到进入管理后台的入口。普通用户没有后台权限，即使手动访问 `/_admin` 也会被后端拒绝。

如果服务启动前环境变量或证书不完整，面板会处于未启用状态；先看 `journalctl -u uniproxy`，不要反复删除数据库。

## 9. 添加节点和生成线路

1. 管理员登录，打开“节点面板”，点击“新增节点”。
2. 选择 `VPS` 或 `NAT`。
3. 填写节点名称、SSH 地址、SSH 端口、认证方式，以及公网 HTTPS 端口/内部端口。
4. NAT 示例：服务商设置 `30000 -> 80`，就填公网端口 `30000`、内部端口 `80`。成功后页面会显示实际使用的内部端口。
5. 提交后，主控机会创建节点 DNS、申请节点证书、通过 SSH 安装并测试 Nginx。首次部署需要几分钟。
6. 添加完成后，在“邀请码管理”创建邀请码，再把邀请码发给使用者。

普通用户注册后，在首页填完整源站地址（建议 `https://emby.example.com`）、选择节点并生成线路。线路地址可以复制到播放器；用户备注只用于自己的记录。

### 源站格式

使用完整的 `https://域名`。不要填带路径、查询参数、用户名密码的 URL；不要把面板域名、节点域名或内网地址当作源站。非标准端口只有在面板允许列表中才会接受。

## 10. 升级、备份和回滚

升级前先备份数据库和环境文件：

```bash
install -d -m 0700 /var/lib/uniproxy/backups
cp -a /var/lib/uniproxy/panel.db /var/lib/uniproxy/backups/panel.db.$(date +%Y%m%d-%H%M%S)
cp -a /root/.secrets/uniproxy-panel.env /var/lib/uniproxy/backups/
```

更新代码并重启：

```bash
cd /opt/uniproxy
git fetch origin
git pull --ff-only origin main
/opt/uniproxy/.venv/bin/pip install -U aiohttp cryptography
systemctl restart uniproxy
nginx -t && systemctl reload nginx
```

如果新版本无法启动，先查看 `journalctl -u uniproxy` 和 `nginx -t`，再使用已确认的 Git 提交和数据库备份回滚。不要在生产机执行不加确认的 `git reset --hard`。

## 11. 常见报错

| 报错 | 处理方式 |
|---|---|
| `acme.sh: not found` | 在主控机安装 acme.sh，确认 `/root/.acme.sh/acme.sh` 可执行。 |
| `openssl: not found` | 在显示该日志的机器安装 `openssl`。主控机和节点都可能缺少。 |
| `没有可管理的 DNS 区域` / `invalid domain` | 检查 Token 的 Zone Read/DNS Edit 权限，以及 `AUTO_NODE_ZONE` 是否填根 Zone。 |
| `SSL_CTX_load_verify_locations ... ca-bundle.pem` | 旧节点缺少 CA bundle。重新用当前版本部署节点，或在节点安装系统 CA 后再测试 Nginx。 |
| `getgrnam("uniproxy-nginx") failed` | 节点的隔离 Nginx 用户未创建完成。确认使用 root SSH，重新部署该节点。 |
| NAT 节点探测失败或 Cloudflare 524 | 检查公网端口是否真的映射到页面显示的内部端口；小内存节点也可能被系统 OOM 杀掉。 |
| `apt ... lock` | 另一个 apt/dpkg 正在运行，等待结束后重试，不要同时启动多个包管理器。 |
| `netlink ... Operation not permitted` | NAT/容器没有管理 nftables 的权限。出站防护是加固项，不能在无权限的容器中强行安装；先保证 Nginx 部署成功。 |
| `invalid request origin` | 更新到当前版本并重启主控服务，刷新旧页面；Nginx 的 `PANEL_PUBLIC_ORIGIN` 必须与浏览器访问的 HTTPS 主域完全一致。 |
| `节点清理未完成` | 新版本会保留待重试记录。SSH 已经无法连接时，先在 Cloudflare 删除项目 DNS，再在后台重试或确认删除记录。 |

查看详细日志：

```bash
journalctl -u uniproxy -f
tail -f /var/log/nginx/error.log
```

## 12. 交付给使用者

部署完成后只需要发给使用者三样东西：主站地址、邀请码、简短说明（注册 → 登录 → 填源站 → 选节点 → 复制线路）。不要把 Cloudflare Token、管理员密码、SSH 密码、数据库或证书私钥发给使用者。
