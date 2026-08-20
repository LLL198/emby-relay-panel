# emby-relay-panel

基于 Nginx 的 Emby 反代管理面板，包含节点部署、线路管理、用户与邀请码、流量统计和证书管理。

## 一键部署

适用于全新的 Debian/Ubuntu 主控机。部署前准备：

- 一个已解析到主控机的面板域名
- 公网 TCP 80、443
- 一个用于节点子域名的 Cloudflare Zone
- Cloudflare API Token（Zone Read + DNS Edit，可稍后填写）

使用 root 运行：

```bash
curl -fsSL https://raw.githubusercontent.com/LLL198/emby-relay-panel/main/deploy/install.sh | bash
```

脚本会询问面板域名、节点根域名、管理员账号和 Cloudflare Token，并自动完成：

- 安装 Nginx、Python、SSH 等依赖
- 申请并安装面板 HTTPS 证书
- 配置证书自动续期
- 创建 Python 环境和 systemd 服务
- 启动面板并验证登录页

未填写管理员密码时，初始账号为 `admin`，密码为 `123456`，首次登录后修改。

## 使用流程

1. 管理员登录并进入管理后台。
2. 在“节点面板”添加 VPS 或 NAT 节点。
3. 创建邀请码并交给使用者注册。
4. 使用者填写 Emby 源站、选择节点并生成线路。
5. 在线路管理和用户管理中查看状态与流量。

面板域名与节点根域名可以不同。例如：

```text
面板：panel.example.com
节点：n-xxx.example.net、*.n-xxx.example.net
```

面板证书通过 HTTP 自动申请，不依赖 Cloudflare Token；Cloudflare Token 只用于创建节点 DNS 和节点证书。

## 运行要求

- 主控机：Debian/Ubuntu，建议 1 GB 内存
- 节点：Debian、Ubuntu 或 Alpine，可使用普通 VPS 或 NAT 机器
- 主控机到节点能够连接 root SSH
- Emby 源站使用可验证的 HTTPS 证书

## 主要文件

- `panel.py`：节点、线路、用户、证书和流量管理
- `uniproxy.py`：登录、用户页面和 HTTP 服务
- `origin_security.py`：源站地址检查
- `nginx_renderer.py`：节点线路 Nginx 配置生成
- `deploy/install.sh`：一键部署脚本
- `uniproxy.service`：systemd 服务模板

详细步骤、升级和常见报错见 [USAGE.md](USAGE.md)。
