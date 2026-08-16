# UniRelay 新手教程（照着做）

这份教程分成两种情况：

- 你只是使用别人已经搭好的面板：只看 **第 1 节**。
- 你是管理员，要自己部署或添加节点：从 **第 2 节**开始。

所有地址、密码和域名都是示例，请换成自己的内容。

## 1. 普通用户：注册、登录、复制线路

### 1.1 注册账号

1. 打开管理员发给你的主站地址，例如 `https://sh.example.com/`。
2. 点击“邀请码注册”。
3. 填写邀请码、账号、密码，点击注册。
4. 注册成功后会自动登录；如果没有自动登录，再回到登录页登录一次。

账号和密码没有复杂的格式限制，但不要使用别人能猜到的密码。

### 1.2 使用线路

登录后，页面上会看到“我的线路”：

- **原线路（源站）**：管理员提供的原始地址，仅用于查看。
- **反代线路（访问地址）**：真正给 Emby 或播放器使用的地址。
- 点击“复制”，把反代线路粘贴到播放器里。
- “备注”只给自己看，例如“手机”“电视”“家庭网络”。

播放器提示“地址格式错误”时，确认复制的是完整的 `https://...` 地址，不要复制原线路、后台地址或带多余空格的内容。

## 2. 管理员：添加一个节点

登录 `https://你的主站/_admin`，打开左侧 **节点面板**，找到“新增节点”。只需要按下面填写：

| 表单项 | 怎么填 |
|---|---|
| 节点名称 | 自己容易认出的名字，例如 `香港 1` |
| 网络类型 | 独立公网 IP 选“普通 VPS”；端口映射机选“NAT” |
| 服务器公网 IP | SSH 连接时使用的公网 IP，不要填内网 IP |
| SSH 端口 | 服务商给你的 SSH 端口；普通 VPS 通常是 `22` |
| 公网 HTTPS 端口 | 用户从互联网访问的端口；普通 VPS 通常 `443`，NAT 填服务商映射的端口 |
| 内部 HTTPS 端口 | 节点机器里 Nginx 实际监听的端口，通常 `443` |
| SSH 密码 / 私钥 | 二选一，不能同时填，也不能都留空 |

### 2.1 VPS 和 NAT 怎么选

**普通 VPS**：机器有独立公网 IP，通常这样填：

```text
网络类型：普通 VPS
公网 HTTPS 端口：443
内部 HTTPS 端口：443
```

**NAT 机器**：服务商给你“公网端口 → 内部端口”的映射。例如：

```text
服务商映射：30000 → 80
公网 HTTPS 端口：30000
内部 HTTPS 端口：80
```

如果机器里已经安装了 Nginx，面板会先读取它的监听端口，并优先采用检测到的端口。部署成功提示里的“最终采用端口”才是实际结果，请确认服务商映射到这个内部端口。

### 2.2 点击“自动部署并添加”后发生什么

面板会自动完成：

1. 通过 SSH 登录节点。
2. 安装 Nginx、OpenSSL 等依赖。
3. 创建节点域名和 HTTPS 证书。
4. 配置 Nginx 并检查配置。
5. 从主站访问节点，确认节点真的能用。

第一次连接可能需要等待几十秒。失败时先看错误最后一行；修正端口、映射或密码后，直接重试即可。

## 3. 管理员：添加一条线路

在左侧 **节点面板 → 新增线路**，只填三项：

| 表单项 | 怎么填 |
|---|---|
| 线路名称 | 小写英文、数字、连字符，例如 `emby-hk` |
| 源站地址 | 完整的 `https://域名`，不要填账号、密码、路径或查询参数 |
| 部署节点 | 选择刚刚添加的节点 |

点击“创建、下发并验证”。成功后复制“公开地址”测试播放。

> 用户自己创建线路时，填写方式相同；只需在主站首页填写源站地址，节点由管理员提供的线路列表决定。

## 4. 管理员：邀请码和用户

左侧菜单分为两个页面：

### 邀请码管理

1. 填“可用次数”“邀请码有效天数”“新账号有效天数”“线路额度”。
2. 点击“创建邀请码”。
3. 下方列表会一直显示邀请码、使用次数和使用者 ID，可以点击复制。
4. 不再需要的邀请码可以删除或停用。

### 用户管理

这里可以看到账号状态、线路数量、流量和最后登录信息。可以：

- 修改线路额度、有效期和备注；
- 停用或恢复账号；
- 重置密码；
- 删除账号及其线路。

## 5. 最常见的报错

### `invalid request origin`

先确认浏览器打开的是主站的 HTTPS 地址，不要直接用 IP、旧域名或节点地址访问。若仍出现，刷新页面后重新登录；当前版本的登录、注册和改密码不要求手动填写 Origin。

### `没有找到可管理的 DNS 区域`

Cloudflare Token 必须同时拥有：

- `Zone / Zone / Read`
- `Zone / DNS / Edit`

资源范围选择实际的主域名，例如 `example.com`，并把服务重启后再添加节点。

### `openssl: not found`

在出问题的节点安装：

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y openssl

# Alpine
sudo apk add openssl
```

### `Could not get lock /var/lib/apt/lists/lock`

节点正在自动更新。等一两分钟再重试，不要删除 lock 文件。

### `nginx -t` 失败

登录节点执行：

```bash
sudo nginx -t
sudo journalctl -u nginx -n 100 --no-pager
```

把最后一段错误发给管理员，不要直接删除整个 `/etc/nginx`。

### `524`、超时或拖动视频断流

先确认节点配置至少有 **128 MB 内存**，NAT 映射没有限速，且源站允许节点出口 IP。小内存 NAT 机同时跑 Nginx、证书续期和播放器长连接时容易超时。

### 节点删除时提示 SSH 连接失败

如果 SSH 已经失效、机器已删或端口拒绝连接，管理员可以选择“从面板移除”。这只会删除主站记录和 DNS；远端机器不可达时，远端残留文件无法自动清理。

## 6. 管理员首次部署（已经有面板的可跳过）

主站建议使用 Debian、Ubuntu 或 Alpine，并准备一个已经解析到主站的域名。

### 6.1 安装依赖

```bash
sudo apt update
sudo apt install -y python3 python3-pip nginx openssl curl openssh-client sshpass
python3 -m pip install --break-system-packages aiohttp cryptography
```

### 6.2 下载项目

```bash
cd /opt
sudo git clone https://github.com/LLL198/emby-relay-panel.git uniproxy
cd /opt/uniproxy
```

### 6.3 创建配置文件

先生成三个随机值：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

创建 `/root/.secrets/uniproxy-panel.env`：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=换成你的后台密码
AGENT_TOKEN=填第一条命令的结果
INVITE_CODE_ENCRYPTION_KEY=填第二条命令的结果
NODE_CREDENTIAL_ENCRYPTION_KEY=填第三条命令的结果
PANEL_DB_PATH=/var/lib/uniproxy/panel.db
```

```bash
sudo install -d -m 700 /root/.secrets /var/lib/uniproxy
sudo chmod 600 /root/.secrets/uniproxy-panel.env
```

### 6.4 Cloudflare Token（中文界面）

如果要让面板自动创建节点域名和证书，在 Cloudflare 创建 **自定义 API Token**，权限只选：

```text
区域 → DNS → 编辑
区域 → 区域 → 读取
区域资源 → 包括 → 特定区域 → 你的主域名
```

例如主域名是 `example.com`，区域资源就选择 `example.com`，不要选择“所有区域”。Token 只复制到主站配置文件，不要放进 Git 或发到聊天里。

在主控机安装证书工具，并把 Token 放到项目指定的 root 文件：

```bash
curl https://get.acme.sh | sh
sudo install -o root -g root -m 600 /dev/null /opt/uniproxy/acme-account.conf
sudo nano /opt/uniproxy/acme-account.conf
```

文件里只写这一行（把引号里的内容换成你的 Token）：

```text
SAVED_CF_Token='粘贴 Cloudflare Token'
```

保存退出后，检查权限：

```bash
sudo chmod 600 /opt/uniproxy/acme-account.conf
```

### 6.5 修改域名和证书路径

编辑 `uniproxy.service`，至少修改：

```ini
Environment=PROXY_DOMAIN_SUFFIX=sh.example.com
Environment=AUTO_NODE_ZONE=example.com
Environment=TLS_CERT_FILE=/etc/letsencrypt/live/sh.example.com/fullchain.pem
Environment=TLS_KEY_FILE=/etc/letsencrypt/live/sh.example.com/privkey.pem
```

证书文件必须真实存在；主站 Nginx 的 80、443 端口也要放行。

### 6.6 启动

```bash
sudo install -m 644 uniproxy.service /etc/systemd/system/uniproxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now uniproxy
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl status uniproxy --no-pager
```

打开：

```text
用户页面：https://你的主站域名/
管理后台：https://你的主站域名/_admin
```

## 7. 安全提醒（只记住这几条）

- 不要把密码、Cloudflare Token、数据库、证书或私钥提交到 Git。
- `/root/.secrets/uniproxy-panel.env` 权限保持 `600`。
- Cloudflare Token 只给当前 DNS 区域的读取和 DNS 编辑权限。
- 主站后台密码、SSH 密码和用户密码不要使用同一个值。
- 更新前先备份数据库：

```bash
sudo cp -a /var/lib/uniproxy/panel.db /var/lib/uniproxy/panel.db.backup
```

更新后：

```bash
cd /opt/uniproxy
sudo git pull --ff-only origin main
sudo systemctl restart uniproxy
```
