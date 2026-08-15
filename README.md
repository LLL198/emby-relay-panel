# UniRelay

UniRelay 是一个基于 Nginx 的反向代理节点和用户管理面板，支持普通 VPS、NAT 节点、Cloudflare DNS 自动配置、HTTPS 证书、邀请码、用户线路和流量统计。

新手请先阅读：[USAGE.md 使用教程](USAGE.md)

## 项目文件

- `uniproxy.py`：主服务、用户页面和反向代理入口
- `panel.py`：管理后台、节点/线路/用户/邀请码管理
- `uniproxy.service`：systemd 服务模板
- `deploy/`：主站 Nginx 配置和安全配置
- `remote-node-nginx-base.conf`：远程节点 Nginx 基础模板
- `convert_remote_routes.py`：旧线路迁移辅助脚本

运行时的环境变量、数据库、Cloudflare Token、证书和 SSH 密钥不应提交到 Git。
