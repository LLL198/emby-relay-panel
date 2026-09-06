# Nginx HTTPS 监听识别回归修复

## 目标

修复已有 Nginx 节点在高位 HTTPS 端口运行时被误判为“未确认 HTTPS”的问题，并让普通 HTTP Nginx 节点能够在不接管原服务的前提下使用独立端口部署，避免错误回退到 443 或直接中止。

## 根因

远端探测此前只保留 `include` 和 `listen` 行，并且只把 `listen ... ssl;` 视为 HTTPS。旧版 Nginx 常见的 `listen 54675;` 搭配同一 `server` 块或上级 `http` 块中的 `ssl on;` 会因此丢失协议上下文，最终把真实 HTTPS 端口误判为普通端口。实际节点 `20.63.208.183:54675` 的公网 TLS 握手也失败，说明它当前确实不能安全作为 HTTPS 前置，不能简单绕过检查。

## 实现

- 保留 Nginx 配置中的花括号、`ssl on;` 和相关 SSL 指令，让面板能够关联 `server` 块。
- 统一解析 IPv4、IPv6 及显式 `listen ... ssl` 端口。
- 同时识别现代 `listen ... ssl;` 与旧式 `ssl on;`，优先选择真实 HTTPS 的非 80 端口；没有 HTTPS 时不进入共享前置分支。
- 已有 Nginx 仅为普通 HTTP 时，保留原服务并自动切换到独立高位端口；只有用户自定义公网端口与旧 HTTP 监听冲突且无法安全推断映射时才提示改端口。

## 验证标准

- 现代 `listen 54675 ssl;`、旧式 `listen 54675;` + `ssl on;`、`http` 级 `ssl on;` 均识别为 54675。
- 同时存在 80 和 54675 时不选择 80；纯 HTTP 配置仍不能冒充 HTTPS。
- 普通 HTTP Nginx 节点不停止原服务，自动部署独立 Nginx；默认公网/内部端口与旧监听冲突时会自动换用新的高位端口。
- 执行语法编译检查和解析回归测试，并在主控面板部署后检查服务、Nginx 配置及 HTTPS 健康页。

## 进度

- [x] 定位远端探测丢失旧式 SSL 上下文的根因
- [x] 修复配置保留与监听端口识别
- [x] 本地回归及主控面板部署验证

## 风险

无法直接使用本轮对话中的节点凭据重跑 `jp` 节点，因此节点本身仍需由用户在面板重新发起一次部署；主控面板逻辑和远端配置探测可先独立验证。

## 验证记录

- `py_compile`、`git diff --check` 通过；现代 `listen ... ssl`、旧式 server/http 级 `ssl on`、IPv6 高位端口、80 与高位端口并存及纯 HTTP 配置回归通过。
- 主控面板已备份后部署，线上 `uniproxy`/`nginx` active，`nginx -t` 成功，`https://fandai.dremby.com/login` 最终返回 200，部署后服务错误日志无新增记录。
- 线上备份：`/opt/uniproxy/.deploy-backup-20260906040742-orange`。未使用节点凭据，未触发节点新增、删除或部署。

## 后续回归

- [ ] 重新发起 `jp` 节点部署，确认 HTTP-only Nginx 分支自动使用独立端口并完成公网端口验证。
