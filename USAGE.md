# emby-relay-panel 部署与使用

## 1. 部署前准备

主控机使用 Debian/Ubuntu，并准备：

- 公网 IP
- 已解析到主控机的面板域名，例如 `panel.example.com`
- 放行公网 TCP 80、443
- 一个由 Cloudflare 管理的节点根域名，例如 `example.net`
- Cloudflare API Token：Zone Read + DNS Edit

面板域名和节点根域名可以属于不同域名。Cloudflare Token 只需要管理节点根域名。

DNS 示例：

```text
panel.example.com  A  主控机公网 IP
```

面板域名开不开 Cloudflare 代理都可以。不开代理时直接使用主控机证书；开启代理时建议将 Cloudflare SSL 模式设为“完全（严格）”。

## 2. 一键部署

在全新的主控机上使用 root 运行：

```bash
curl -fsSL https://raw.githubusercontent.com/LLL198/emby-relay-panel/main/deploy/install.sh | bash
```

按提示填写：

- 面板域名：如 `panel.example.com`
- 节点根域名：如 `example.net`
- 管理员用户名
- 管理员密码：留空时使用 `123456`
- Cloudflare API Token：可留空，添加自动节点前再配置

脚本会自动安装依赖、申请 HTTPS 证书、配置 Nginx、创建服务和证书续期定时器。证书使用 HTTP 验证，因此面板域名必须已经解析，公网 80 端口也必须可访问。

完成后打开：

```text
https://你的面板域名
```

首次登录后按页面提示修改初始密码。

## 3. 后补 Cloudflare Token

如果部署时没有填写 Token，在主控机创建 `/opt/uniproxy/acme-account.conf`：

```bash
printf "SAVED_CF_Token='%s'\n" '你的Token' > /opt/uniproxy/acme-account.conf
chmod 0600 /opt/uniproxy/acme-account.conf
systemctl restart uniproxy
```

Token 对应的 Zone 必须与安装时填写的节点根域名一致。

## 4. 添加节点

登录管理员账号，进入“管理后台 → 节点面板 → 新增节点”。

需要填写：

- 节点名称
- VPS 或 NAT
- 服务器公网 IP
- SSH 端口
- 公网 HTTPS 端口
- 内部 HTTPS 端口
- root 密码或私钥

普通 VPS 通常填写：

```text
公网 HTTPS 端口：443
内部 HTTPS 端口：443
```

NAT 示例，服务商端口映射为 `30000 → 80`：

```text
公网 HTTPS 端口：30000
内部 HTTPS 端口：80
```

如果节点已经安装并监听 Nginx，面板会优先使用检测到的内部端口。部署成功后页面会显示实际使用的端口，按这个端口设置 NAT 映射即可。

自动部署会完成节点 DNS、证书、Nginx 和健康检查。节点可以使用 Debian、Ubuntu 或 Alpine。

## 5. 用户和线路

管理员先在“邀请码管理”创建邀请码。使用者注册后，在首页：

1. 填写完整 Emby 源站，例如 `https://emby.example.com`。
2. 选择节点。
3. 可填写线路备注。
4. 创建并复制线路地址到播放器。

线路源站应使用 HTTPS 域名，不要填写路径、查询参数、面板域名、节点域名或内网地址。

部署失败或仍在等待部署的线路，即使节点已经离线也可以从面板删除；页面会提示远端清理是否确认。已成功部署的线路仍会先清理节点配置，避免遗留可用入口。

## 6. 证书自动续期

面板证书由 acme.sh 管理，每天检查一次，到期前自动续期并 reload Nginx。

查看状态：

```bash
systemctl status emby-panel-cert-renew.timer --no-pager
systemctl list-timers emby-panel-cert-renew.timer --no-pager
/root/.acme.sh/acme.sh --info -d panel.example.com --ecc
```

续期依赖：

- 面板域名继续指向主控机
- 公网 80 端口可访问
- Nginx 中保留 `/.well-known/acme-challenge/` 路径

节点证书使用 Cloudflare DNS 验证，与面板证书相互独立。

## 7. 查看服务状态

```bash
systemctl status uniproxy --no-pager
systemctl status nginx --no-pager
journalctl -u uniproxy -n 100 --no-pager
nginx -t
```

Python 服务只监听 `127.0.0.1:8787`，公网访问统一经过 Nginx。

## 8. 升级

先备份数据库：

```bash
install -d -m 0700 /var/lib/uniproxy/backups
cp -a /var/lib/uniproxy/panel.db \
  /var/lib/uniproxy/backups/panel.db.$(date +%Y%m%d-%H%M%S)
```

更新并重启：

```bash
cd /opt/uniproxy
git pull --ff-only origin main
/opt/uniproxy/.venv/bin/pip install -U aiohttp cryptography
/opt/uniproxy/.venv/bin/python -m py_compile panel.py uniproxy.py origin_security.py
systemctl restart uniproxy
nginx -t && systemctl reload nginx
```

## 9. 常见报错

| 报错 | 处理 |
|---|---|
| 面板证书申请失败 | 检查域名解析、公网 80 端口和安全组，然后重新运行证书命令。 |
| `acme.sh: not found` | 执行 `curl -fsSL https://get.acme.sh \| sh`。 |
| `openssl: not found` | 在报错的主控机或节点安装 `openssl`。 |
| `没有可管理的 DNS 区域` | 检查节点根域名和 Token 的 Zone Read/DNS Edit 权限。 |
| `apt ... lock` | 系统正在运行其他 apt/dpkg 任务，等待结束后重试。 |
| `getgrnam("uniproxy-nginx") failed` | 节点部署未完成，确认 root SSH 后重新添加节点。 |
| `ca-bundle.pem` 不存在 | 在旧节点安装系统 CA，或使用当前版本重新部署节点。 |
| NAT 节点探测失败 | 检查公网端口是否映射到页面显示的内部端口。 |
| Cloudflare 524 | 检查节点是否离线、内存不足、端口映射错误或请求处理过久。 |
| 删除失败线路时报远端清理未确认 | 线路记录仍会删除；提示表示节点上的残留配置无法确认。 |

主控日志：

```bash
journalctl -u uniproxy -f
```

Nginx 日志：

```bash
tail -f /var/log/nginx/error.log
```

## 10. 主要路径

```text
/opt/uniproxy                         项目目录
/var/lib/uniproxy/panel.db            数据库
/root/.secrets/uniproxy-panel.env     运行配置
/opt/uniproxy/acme-account.conf       Cloudflare Token
/etc/letsencrypt/live/<面板域名>/     面板证书
/etc/systemd/system/uniproxy.service  主控服务
```

`uniproxy` 是兼容旧版本保留的服务名和运行路径，项目名称为 `emby-relay-panel`。
