# emby-relay-panel

基于 Nginx 的 Emby 反代面板。这个仓库是**部署代码**，不是一个已经开通的在线服务；拿到仓库后，需要在自己的主控机、域名和 Cloudflare 账号上完成安装。

完整部署手册见 [USAGE.md](USAGE.md)。下面是部署流程总览。

## 项目怎么工作

```text
用户浏览器/播放器
        |
        v
主控机 Nginx + Python 面板  <---- Cloudflare DNS/证书 API
        |
        +---- 节点 Nginx（每台 VPS/NAT 一台）----> Emby 源站
```

- 主控机保存用户、邀请码、节点和线路元数据；SQLite 数据库默认位于 `/var/lib/uniproxy/panel.db`。
- 节点由后台通过 SSH 自动部署独立的 Nginx，并为节点域名申请/安装证书。
- Cloudflare Token 只应放在主控机的权限文件中；不要提交到 Git，也不要发给别人。
- 反代线路使用 HTTPS 源站。创建线路时会检查源站域名和公网地址，避免把面板变成内网开放代理。

## 部署前准备

你需要准备：

1. 一台 Debian/Ubuntu/Alpine 主控机，能监听 80/443，建议至少 1 GB 内存。
2. 一个主站域名，例如 `sh.example.com`，并把 DNS 指向主控机。
3. 一个 Cloudflare Zone，例如 `example.com`，用于创建节点子域名。
4. 一个 Cloudflare API Token：只授予该 Zone 的 **Zone Read** 和 **DNS Edit** 权限。
5. 每台节点的 SSH 地址、端口、root 密码或私钥；NAT 节点还要知道公网端口到内部 HTTPS 端口的映射。
6. 主站自己的 TLS 证书和私钥。主站证书不由本项目自动申请，必须先准备好。

## 快速部署

不要直接把生产密码写进仓库。克隆代码、安装依赖、创建环境文件、配置主站 Nginx 后，再启动 `uniproxy.service`。详细的可复制命令和每个字段的含义都在 [USAGE.md](USAGE.md)。

```bash
git clone https://github.com/LLL198/emby-relay-panel.git /opt/uniproxy
cd /opt/uniproxy
python3 -m venv /opt/uniproxy/.venv
/opt/uniproxy/.venv/bin/pip install aiohttp cryptography
```

主控机还需要可执行的 `acme.sh`；节点部署需要 `nginx`、`openssl`、`curl`、`openssh-client`/`ssh` 等系统工具。

## 首次启动后的行为

- 第一次启动会从 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 创建唯一管理员账号；密码为空时服务不会启用。
- 管理员和普通用户使用同一个 `/login` 页面。管理员登录后，在用户首页看到“管理后台”入口；普通用户直接访问 `/_admin` 会被后端拒绝。
- 管理员先添加节点，再创建邀请码。普通用户用邀请码注册后，可以在首页创建自己的反代线路。

## 仓库目录

- `panel.py`：节点、线路、用户、邀请码、证书和流量管理。
- `uniproxy.py`：面板 HTTP 服务、登录和用户页面。
- `uniproxy.service`：主控机 systemd 服务模板。
- `deploy/`：主站 Nginx 示例、节点 Nginx 模板、日志轮转配置。
- `origin_security.py`：源站 HTTPS 和公网地址校验。
- `tests/`：安全、数据库和回归测试。

项目品牌统一为 `emby-relay-panel`；`uniproxy` 出现在服务名、安装路径、日志和节点隔离用户中，是为了兼容已部署实例的运行时标识，不代表项目仍使用旧品牌。

## 安全注意事项

- `.env`、`panel.db`、`acme-account.conf`、SSH 私钥、证书私钥和日志都不应提交到 Git。
- `ADMIN_PASSWORD`、`AGENT_TOKEN`、两个 Fernet 密钥都要使用随机高熵值，并设置环境文件为 `root:root`、`0600`。
- Cloudflare Token 文件只放在主控机；节点部署接收证书，不需要把该 Token 复制到节点。
- 生产环境请使用 HTTPS；不要把 Python 面板端口 `8787` 直接暴露到公网。

部署、升级、节点添加和常见报错请按 [USAGE.md](USAGE.md) 操作。
