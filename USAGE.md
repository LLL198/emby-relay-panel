# UniRelay 使用教程

这是一份面向新手的部署和日常使用说明。文中的 `example.com`、`panel.example.com`、密码和 Token 都是示例，请替换成自己的值。

## 1. UniRelay 是做什么的

UniRelay 分为三部分：

- **主站**：用户登录、创建线路和访问代理地址。
- **管理后台**：访问 `https://主站域名/_admin`，管理节点、线路、用户和邀请码。
- **节点**：真正连接源站的 VPS 或 NAT 机器。节点可以使用独立公网 IP，也可以使用端口映射。

项目使用 Nginx 生成反代配置。访问源站时会清理常见的客户端 IP/代理链请求头，并保留浏览器和播放器的身份、Range、WebSocket 等功能字段。

## 2. 部署前准备

建议主站使用 Ubuntu 或 Debian，并准备：

1. 一个主站域名，例如 `panel.example.com`。
2. 主站域名的 HTTPS 证书和私钥。
3. 主站服务器的 80、443 端口已放行，8787 只监听本机。
4. 如需自动添加节点，准备 Cloudflare API Token、主控机的 acme.sh，以及节点的 root SSH 登录方式。新增节点时还要从云厂商控制台核对 SSH 主机指纹。

### Cloudflare Token 权限

自动添加节点时，面板会创建节点域名和通配符 DNS 记录，并由主控机通过 DNS-01 申请证书，再只把证书下发到节点。Cloudflare Token 只留在主控机，不会复制到节点。Token 至少需要：

- `Zone / DNS / Edit`
- `Zone / Zone / Read`
- 区域资源选择实际管理的域名，例如 `example.com`

Token 不要写进源码、截图、Git 或聊天记录。主控机的 `/opt/uniproxy/acme-account.conf` 只允许 root 读取，权限必须为 `600`；节点不应出现该文件或 `SAVED_CF_Token`。

新增节点前，在云厂商控制台复制该实例的 SSH `SHA256:...` 主机指纹。面板会使用 `ssh-keyscan` 取回公钥、核对指纹并写入独立 `known_hosts`，指纹不匹配或未核对时不会发送 SSH 密码/私钥。

## 3. 安装系统依赖

在主站执行：

```bash
sudo apt update
sudo apt install -y python3 python3-pip nginx openssl curl openssh-client sshpass
python3 -m pip install --break-system-packages aiohttp cryptography
# 主控机需要已安装 /root/.acme.sh/acme.sh（用于集中签发节点证书）
```

如果系统不支持 `--break-system-packages`，可以使用虚拟环境安装 Python 依赖，再把 `uniproxy.service` 中的 Python 路径改为虚拟环境里的路径。

## 4. 放置项目文件

```bash
sudo install -d -m 700 /opt/uniproxy /root/.secrets /var/lib/uniproxy
sudo cp uniproxy.py panel.py /opt/uniproxy/
sudo cp uniproxy.service /etc/systemd/system/uniproxy.service
sudo chmod 700 /opt/uniproxy
```

如果使用仓库部署，也可以先克隆：

```bash
cd /opt
sudo git clone https://github.com/LLL198/UniRelay.git uniproxy
cd /opt/uniproxy
```

## 5. 配置环境变量

先生成随机值：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

创建 `/root/.secrets/uniproxy-panel.env`：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=请替换为管理后台密码
AGENT_TOKEN=请再生成一个随机值
INVITE_CODE_ENCRYPTION_KEY=请填入第二条命令生成的Fernet密钥
NODE_CREDENTIAL_ENCRYPTION_KEY=请再生成一条Fernet密钥，用于加密节点 SSH 密码

# 可选：不填时使用默认路径
PANEL_DB_PATH=/var/lib/uniproxy/panel.db
```

设置权限：

```bash
sudo chmod 600 /root/.secrets/uniproxy-panel.env
```

说明：

- `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 用于管理后台的 Basic Auth。
- `AGENT_TOKEN` 用于本机健康/流量采集接口，泄露后应立即更换。
- `INVITE_CODE_ENCRYPTION_KEY` 用来加密长期邀请码。项目运行后不要随意更换，否则旧邀请码无法解密显示。

## 6. 配置主站域名和证书

编辑 `uniproxy.service` 中这些值：

```ini
Environment=PROXY_DOMAIN_SUFFIX=panel.example.com
Environment=AUTO_NODE_ZONE=example.com
Environment=PUBLIC_HTTPS_PORT=443
Environment=TLS_CERT_FILE=/etc/letsencrypt/live/panel.example.com/fullchain.pem
Environment=TLS_KEY_FILE=/etc/letsencrypt/live/panel.example.com/privkey.pem
Environment=LISTEN_HOST=127.0.0.1
Environment=LISTEN_PORT=8787
```

其中：

- `PROXY_DOMAIN_SUFFIX` 是主站域名后缀。
- `AUTO_NODE_ZONE` 是自动创建节点 DNS 记录的 Cloudflare 区域。
- `TLS_CERT_FILE` 和 `TLS_KEY_FILE` 必须指向实际存在的证书和私钥。

如果主站 Nginx 使用 `deploy/` 中的配置，请同时把其中的域名和证书路径改成自己的值。使用 Cloudflare Origin Pull 时，确认 `ssl_client_certificate` 指向实际存在的 CA 文件；不使用时不要保留 `ssl_verify_client on`，否则普通浏览器会被拒绝。

## 7. 启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now uniproxy
sudo systemctl status uniproxy
```

查看实时日志：

```bash
sudo journalctl -u uniproxy -f
```

确认主站 Nginx 配置：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

浏览器打开：

- 用户页面：`https://panel.example.com/`
- 管理后台：`https://panel.example.com/_admin`

## 8. 第一次配置管理后台

### 8.1 添加节点

进入“节点面板”，填写节点名称、网络类型、服务器公网 IP、SSH 端口和 SSH 密码/私钥二选一。

- **普通 VPS**：选择“普通 VPS”，公网 HTTPS 端口使用 `443`。
- **NAT 机**：选择“NAT 机”，填写服务商映射的公网 HTTPS 端口，并确认该端口转发到节点内部 `443`。

自动部署需要：

- SSH 账号可以执行 root 操作；
- 节点能访问软件源、Cloudflare DNS 和 Let's Encrypt；
- Cloudflare Token 的区域和权限正确；
- NAT 节点的映射端口已经开放。

添加后点击“检查”。第一次 SSH 连接偶尔会因为系统刚启动而等待几秒，重试即可。

### 8.2 添加线路

在节点面板创建线路，填写：

- 线路名称：小写字母、数字和连字符；
- 源站地址：例如 `https://media.example.com`；
- 目标节点。

源站地址不要包含账号密码、路径、查询参数或片段。创建成功后，使用面板显示的 HTTPS 代理地址。

### 8.3 创建邀请码和用户

1. 打开“邀请码管理”，创建长期邀请码。
2. 可以看到邀请码、使用次数和使用者 ID，也可以点击复制或删除。
3. 用户打开主站的“邀请码注册”，填写邀请码、用户名和密码。
4. 登录后可以看到自己拥有的线路，并创建新的线路备注。

用户停用后会被退出登录；删除用户会同时删除该用户的线路，请谨慎操作。

## 9. 流量统计

节点面板显示节点代理用量，用户管理显示每个用户的代理用量，单位为 GB。面板每隔约 60 秒从节点的 Nginx 统计日志读取数据，因此刚产生的流量可能需要等待一轮采集。

统计从启用采集后开始，不会自动补算部署前的历史流量。

## 10. 常见问题

### “没有找到可管理的 DNS 区域”

检查 `AUTO_NODE_ZONE` 是否与 Cloudflare 中的区域完全一致，并确认 Token 有该区域的 `Zone Read` 和 `DNS Edit` 权限。Token 资源不能只授权到错误的域名。

### `openssl: not found`

在出问题的节点安装 OpenSSL：

```bash
sudo apt install -y openssl
# Alpine：sudo apk add openssl
```

新版本自动部署脚本会主动安装 OpenSSL。

### `Could not get lock /var/lib/apt/lists/lock`

说明节点正被系统更新进程占用 apt。等待系统更新完成后再点一次部署，不要删除 lock 文件。

### 公网返回 HTTP 403

这通常是源站或源站 WAF 拒绝了节点出口 IP，不是线路格式错误。将节点出口 IP 加入源站白名单，或更换节点后重新下发线路。

### `nginx -t` 失败

先查看完整错误位置：

```bash
sudo nginx -t
sudo journalctl -u nginx -n 100 --no-pager
```

确认生成配置位于 `/etc/nginx/conf.d/`，不要把 `server { ... }` 配置直接放到不允许 `server` 指令的上下文中。

### 播放器提示地址格式错误

确认使用的是面板生成的完整 `https://` 地址，不要把后台地址、带路径的源站地址或 NAT 内网地址当成公网线路地址。

## 11. 安全建议

- `/root/.secrets/uniproxy-panel.env`、`acme-account.conf`、证书和 SSH 私钥全部设置为 `600`。
- 8787 只监听 `127.0.0.1`，防火墙只开放必要的 80、443 和 SSH 端口。
- Cloudflare Token 使用最小权限，泄露后立即撤销并重新生成。
- 不要把数据库、日志、证书、私钥或 Token 提交到 Git。
- 管理员密码、代理 Token 和邀请码加密密钥要分别保存，不能都使用同一个值。

## 12. 更新项目

如果项目是通过 Git 克隆的：

```bash
cd /opt/uniproxy
sudo git pull --ff-only origin main
sudo systemctl restart uniproxy
sudo systemctl status uniproxy
```

更新前建议备份数据库：

```bash
sudo cp -a /var/lib/uniproxy/panel.db /var/lib/uniproxy/panel.db.backup
```
