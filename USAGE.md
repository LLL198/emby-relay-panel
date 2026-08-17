# emby-relay-panel 新手教程

这份教程按“照着填就能用”的方式写。所有域名、IP、密码都是示例，请换成自己的内容。

## 1. 普通用户：注册并生成线路

如果管理员已经把主站搭好，你只需要看这一节。

### 1.1 注册和登录

1. 打开管理员发来的主站，例如 `https://sh.example.com/`。
2. 点击“邀请码注册”。
3. 填写邀请码、用户名、密码和确认密码。
4. 点击“注册并登录”。注册成功后会自动登录。
5. 以后从同一个登录页登录。默认会保持登录 90 天，也可以取消勾选。

管理员账号也使用这个登录页；普通用户不会看到管理后台入口。

### 1.2 生成访问地址

登录后，在首页填写：

| 位置 | 填什么 |
|---|---|
| 原始网站地址 | 完整的 `https://域名`，例如 `https://emby.example.com` |
| 节点 | 选择一个节点，先点“重新测试延迟”可以看延迟 |
| 线路备注 | 可选，例如“手机”“电视”“家庭网络” |

点击“生成访问地址”，然后在“我的线路”中复制 **反代线路（访问地址）**。

播放器必须填复制出来的完整 `https://...` 地址。不要填原线路、主站地址、后台地址，也不要把地址后的空格一起复制。

## 2. 管理员：第一次登录

管理员和普通用户共用登录页：

1. 打开主站首页并登录管理员账号。
2. 进入普通用户首页。
3. 右上角点击“管理后台”。

管理员账号不是通过邀请码注册的。第一次部署时，账号来自主控机环境文件：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=请换成强密码
```

首次启动会自动创建这个管理员。管理员可以在首页“账号安全”修改密码；修改后所有旧会话都会失效。以后如果明确修改环境文件里的 `ADMIN_USERNAME` 或 `ADMIN_PASSWORD`，重启服务会作为应急方式同步新账号密码。

## 3. 管理员：添加节点

进入 **管理后台 → 节点面板 → 新增节点**。

### 3.1 表单怎么填

| 表单项 | 普通 VPS | NAT 机器 |
|---|---|---|
| 节点名称 | 自己容易认出的名字，例如 `香港 1` | 同左 |
| 网络类型 | 选“普通 VPS” | 选“NAT” |
| 服务器公网 IP | SSH 连接用的公网 IP | 服务商提供的入口 IP，不要填内网 IP |
| SSH 端口 | 通常是 `22` | 填服务商给的 SSH 入口端口 |
| 公网 HTTPS 端口 | 通常 `443` | 填服务商映射的公网端口 |
| 内部 HTTPS 端口 | 通常 `443` | 填映射目标端口 |
| SSH 密码 / 私钥 | 二选一 | 二选一 |

密码和私钥不能同时填，也不能都留空。

### 3.2 端口例子

普通 VPS：

```text
公网 HTTPS 端口：443
内部 HTTPS 端口：443
```

NAT 服务商如果给你：

```text
公网 TCP 30000 → 机器内部 TCP 80
```

就填写：

```text
公网 HTTPS 端口：30000
内部 HTTPS 端口：80
```

如果远端已经安装 Nginx，面板会先读取它的监听端口，并优先使用检测到的端口，忽略表单里填写的内部端口。部署成功提示里的“最终采用端口”才是最终结果，请确认服务商映射到这个端口。

### 3.3 点击自动部署后

面板会自动：

1. 通过 SSH 登录节点；
2. 安装或准备 Nginx、OpenSSL、CA 证书等依赖；
3. 创建节点域名和 HTTPS 证书；
4. 写入 Nginx 配置并执行 `nginx -t`；
5. 从主控机检查公网访问。

第一次部署可能需要几十秒。失败时先看错误最后一行，优先检查 SSH 端口、NAT 映射、密码和安全组。

## 4. 管理员：创建线路和邀请码

### 4.1 创建管理员线路

进入 **节点面板 → 新增线路**，填写三项：

| 表单项 | 填写示例 |
|---|---|
| 线路名称 | `emby-hk`，只能用小写字母、数字和连字符 |
| 源站地址 | `https://emby.example.com`，不要填账号、密码、路径或查询参数 |
| 部署节点 | 选择刚添加的节点 |

点击“创建、下发并验证”。成功后复制公开地址。

### 4.2 创建邀请码

进入 **邀请码管理**：

1. 设置可用次数、邀请码有效天数、新账号有效天数和线路额度。
2. 点击“创建邀请码”。
3. 列表会长期显示邀请码、使用次数、使用者 ID 和用户名，可以点击复制。
4. 不再需要的邀请码可以撤销或删除。

### 4.3 用户管理

进入 **用户管理** 可以查看：

- 账号状态和有效期；
- 已用线路数和线路额度；
- 今日、本月和累计流量；
- 最近登录时间和 IP。

可以停用、恢复、重置普通用户密码、修改额度和删除普通用户。管理员账号不能在这里删除或停用，只能在首页“账号安全”改密码。

## 5. 管理员：第一次部署主控机

已经有可用面板的管理员可以跳过这一节。主控机建议使用 Debian、Ubuntu 或 Alpine，并准备一个已经解析到主控机的域名。

### 5.1 安装依赖

Debian / Ubuntu：

```bash
sudo apt update
sudo apt install -y git python3 python3-pip nginx openssl curl openssh-client sshpass
python3 -m pip install --break-system-packages aiohttp cryptography
```

Alpine：

```bash
sudo apk add git python3 py3-pip nginx openssl curl openssh-client sshpass
python3 -m pip install --break-system-packages aiohttp cryptography
```

### 5.2 下载项目

```bash
cd /opt
sudo git clone https://github.com/LLL198/emby-relay-panel.git uniproxy
cd /opt/uniproxy
```

### 5.3 创建主控配置

先生成三个随机值：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

创建 `/root/.secrets/uniproxy-panel.env`：

```dotenv
ADMIN_USERNAME=admin
ADMIN_PASSWORD=换成强密码
AGENT_TOKEN=填第一条命令的结果
INVITE_CODE_ENCRYPTION_KEY=填第二条命令的结果
NODE_CREDENTIAL_ENCRYPTION_KEY=填第三条命令的结果
PANEL_DB_PATH=/var/lib/uniproxy/panel.db
```

设置权限：

```bash
sudo install -d -m 700 /root/.secrets /var/lib/uniproxy
sudo chmod 600 /root/.secrets/uniproxy-panel.env
```

### 5.4 Cloudflare DNS Token

如果需要自动创建节点域名和证书，在 Cloudflare 创建自定义 API Token，只给当前区域：

```text
区域 → 区域 → 读取
区域 → DNS → 编辑
区域资源 → 包括 → 特定区域 → 你的主域名
```

Token 只放在主控机的 root 文件中，绝对不要放进 Git、截图或聊天记录。项目使用主控机集中签发证书，节点不应保存 Cloudflare Token。

### 5.5 配置域名和启动

编辑 `uniproxy.service`，至少修改以下值：

```ini
Environment=PROXY_DOMAIN_SUFFIX=sh.example.com
Environment=AUTO_NODE_ZONE=example.com
Environment=PANEL_PUBLIC_ORIGIN=https://sh.example.com
Environment=TLS_CERT_FILE=/etc/letsencrypt/live/sh.example.com/fullchain.pem
Environment=TLS_KEY_FILE=/etc/letsencrypt/live/sh.example.com/privkey.pem
```

主站 Nginx 需要把 HTTPS 请求转发到 `127.0.0.1:8787`。可以参考 `deploy/` 中的配置，先把示例域名替换成自己的域名，再检查配置：

```bash
sudo nginx -t
sudo install -m 644 uniproxy.service /etc/systemd/system/uniproxy.service
sudo systemctl daemon-reload
sudo systemctl enable --now uniproxy
sudo systemctl reload nginx
sudo systemctl status uniproxy --no-pager
```

然后打开 `https://你的主站域名/login`，使用环境文件里的管理员账号登录。

## 6. 常见报错

### `invalid request origin`

这是旧版本常见提示。先确认使用当前主域名的 HTTPS 地址，不要用 IP、旧域名或节点域名；刷新页面并重新登录。如果更新后仍然出现，确认主控服务已经重启并且浏览器没有停留在旧页面。

### `没有找到可管理的 DNS 区域`

检查 Cloudflare Token 是否有“区域读取”和“DNS 编辑”权限，资源范围是否选中了正确的主域名。修改 Token 后要重启主控服务。

### `openssl: not found`

在报错的节点安装 OpenSSL：

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y openssl

# Alpine
sudo apk add openssl
```

### `Could not get lock /var/lib/apt/lists/lock`

节点正在自动更新。等待一两分钟后重试，不要手动删除 lock 文件。

### `nginx -t` 或 `ca-bundle.pem` 失败

先在节点检查：

```bash
sudo nginx -t
sudo journalctl -u nginx -n 100 --no-pager
```

旧节点可能还没有系统 CA 文件。把主控更新到最新版后，在节点面板点击“检查”或重新下发线路。

### `524`、超时、拖动视频断流

先检查：

1. NAT 公网端口是否确实映射到最终采用的内部端口；
2. 服务商是否限速；
3. 节点是否内存太小（建议至少 128 MB，播放和证书任务并发时建议更高）；
4. 源站是否允许节点出口 IP。

### 节点删除时 SSH 连接失败

如果机器已经删除或 SSH 端口失效，管理员可以选择从面板移除记录。主控记录和 DNS 会被清理，但远端机器不可达时，远端残留文件无法自动删除。

## 7. 更新和安全

更新前先备份数据库：

```bash
sudo cp -p /var/lib/uniproxy/panel.db \
  "/var/lib/uniproxy/panel.db.backup-$(date -u +%Y%m%dT%H%M%SZ)"
```

从 GitHub 更新并重启：

```bash
cd /opt/uniproxy
sudo git pull --ff-only origin main
sudo systemctl restart uniproxy
sudo nginx -t && sudo systemctl reload nginx
```

永远不要提交或公开：管理员密码、用户密码、Cloudflare Token、数据库、证书、SSH 密钥和节点备份。
