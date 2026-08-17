# emby-relay-panel
emby-relay-panel 是一个基于 Nginx 的反向代理节点和用户管理面板，支持普通 VPS、NAT 节点、Cloudflare DNS 自动配置、HTTPS 证书、邀请码、用户线路和流量统计。

## 不会用？按这个顺序做

1. 先看 [新手使用教程](USAGE.md)。
2. 只是使用线路：从教程第 1 节开始，不需要安装任何东西。
3. 管理员添加节点：只填节点名称、VPS/NAT、IP、SSH 端口、两个 HTTPS 端口和 SSH 密码/私钥。
4. 添加线路：填线路名称、`https://` 源站地址和节点，点“创建、下发并验证”。
5. 用户拿到反代地址后，点击“复制”并粘贴到播放器。

遇到问题，先看教程第 5 节的常见报错，再把错误最后一行发给管理员。

## 项目文件

- `uniproxy.py`：主服务、用户页面和反向代理入口
- `panel.py`：管理后台、节点/线路/用户/邀请码管理
- `uniproxy.service`：systemd 服务模板
- `deploy/`：主站 Nginx 配置和安全配置
- `remote-node-nginx-base.conf`：只返回 404 的安全示例模板；实际线路由面板统一生成
- `convert_remote_routes.py`：旧线路迁移辅助脚本

运行时的环境变量、数据库、Cloudflare Token、证书和 SSH 密钥不应提交到 Git。

安全默认值：用户源站只允许 HTTPS 且会固定经过验证的公网解析地址；上游 TLS 开启证书校验；面板会使用 `__Host-` 会话 Cookie；SSH 首次连接自动记录主机密钥，后续密钥变化会被拒绝。Cloudflare Token 仅用于主控机集中签发证书，不应复制到节点。
