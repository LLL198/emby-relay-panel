# emby-relay-panel

一个给 Emby 使用的 Nginx 反代面板：管理员添加 VPS/NAT 节点，用户注册后自己生成线路。

项目地址：[github.com/LLL198/emby-relay-panel](https://github.com/LLL198/emby-relay-panel)

## 先判断你是哪种用户

### 只是使用线路

你不需要安装项目：

1. 打开管理员发来的主站地址。
2. 使用邀请码注册并登录。
3. 在首页填写原始 Emby 地址，选择节点，点击生成。
4. 在“我的线路”里复制“反代线路”，粘贴到播放器。

详细步骤见 [新手教程](USAGE.md) 的第 1 节。

### 负责管理面板

按这个顺序操作：

1. 在主控机部署项目，并设置 `ADMIN_USERNAME`、`ADMIN_PASSWORD`。
2. 管理员和普通用户使用同一个登录页；管理员登录后，首页右上角会出现“管理后台”。
3. 在“节点面板”添加 VPS 或 NAT 节点。
4. 在“邀请码管理”创建邀请码并发给用户。
5. 在“用户管理”查看账号、线路和流量。

普通用户即使手动打开 `/_admin` 也不能进入后台，权限由后端会话校验，不是只隐藏一个链接。

## 项目包含什么

- `uniproxy.py`：主服务、登录页、用户首页和请求路由
- `panel.py`：节点、线路、用户、邀请码、证书和流量管理
- `uniproxy.service`：主控机 systemd 服务模板
- `deploy/`：主站 Nginx 配置、日志轮转和节点模板
- `origin_security.py`：源站 HTTPS、公网 IP 和 DNS 安全校验
- `tests/`：安全和数据库迁移测试

## 安全注意

不要把以下内容提交到 Git：

- `.env`、数据库和备份
- Cloudflare Token
- 证书、私钥、SSH 密钥和密码

面板会使用 `__Host-` 会话 Cookie；上游默认只允许 HTTPS，并校验证书和公网解析地址；Cloudflare Token 应只放在主控机配置中。

## 遇到问题

先看 [新手教程的常见报错](USAGE.md#6-常见报错)。如果仍然失败，把错误信息最后 20 行发给管理员，不要直接删除 Nginx 配置或数据库。
