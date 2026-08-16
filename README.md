# UniRelay

UniRelay 是一个基于 Nginx 的反向代理节点和用户管理面板，支持普通 VPS、NAT 节点、Cloudflare DNS 自动配置、HTTPS 证书、邀请码、用户线路和流量统计。

新手请先阅读：[USAGE.md 使用教程](USAGE.md)

## 项目文件

- `uniproxy.py`：主服务、用户页面和反向代理入口
- `panel.py`：管理后台、节点/线路/用户/邀请码管理
- `uniproxy.service`：systemd 服务模板
- `deploy/`：主站 Nginx 配置和安全配置
- `remote-node-nginx-base.conf`：只返回 404 的安全示例模板；实际线路由面板统一生成
- `convert_remote_routes.py`：旧线路迁移辅助脚本

运行时的环境变量、数据库、Cloudflare Token、证书和 SSH 密钥不应提交到 Git。

安全默认值：用户源站只允许 HTTPS 且会固定经过验证的公网解析地址；上游 TLS 开启证书校验；面板会使用 `__Host-` 会话 Cookie；SSH 首次连接自动记录主机密钥，后续密钥变化会被拒绝。Cloudflare Token 仅用于主控机集中签发证书，不应复制到节点。
