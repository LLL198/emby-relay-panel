# 小内存节点 APT 部署修复

## 目标

修复 64 MiB 容器节点在自动安装 Nginx 依赖时反复出现 `apt-get ... Killed`，并避免把内存不足误报为包管理器锁等待。

## 证据

- 失败节点的 cgroup `memory.max` 为 64 MiB，`memory.swap.max` 为 64 MiB。
- `memory.events` 已记录 37 次 `oom_kill`，面板日志中的每次 `Killed` 与 OOM 一致。
- 磁盘剩余约 971 MiB，`dpkg --audit` 无异常，也没有持续运行的 apt/dpkg 锁持有者。
- Debian 的 `cron` 会拉入邮件系统和 Perl 等大量依赖，但该节点已有 systemd，重启自启不需要 cron。

## 方案

- Debian/Ubuntu 使用 systemd 时不安装 `cron`，保留非 systemd 环境的兼容回退。
- 使用 `--no-install-recommends`，关闭安装建议、APT 语言索引和 dpkg PTY，并逐个安装依赖以降低峰值内存。
- 低内存时只使用 `/etc/apt/sources.list`，禁用重复的 source parts 和 `deb-src` 索引，进一步降低 APT 解析规模。
- 低内存且已有软件包索引时复用现有索引，减少一次不必要的 `apt update` 峰值。
- 低内存安装时让 APT 只负责下载，跳过 `Preconfiguring packages ...` 的预配置子进程，再由 `dpkg` 分步解包和配置；临时阻止软件包安装脚本启动服务，完成后恢复原状。
- 每次 apt 执行前后读取 cgroup OOM 计数；检测到退出码 137 或 OOM 计数增长时立即停止并给出准确报错，不再重复执行 12 次。
- 只有确认另一个 apt/dpkg 进程仍在运行时才按锁冲突重试；普通网络、仓库或依赖错误直接返回原始错误。
- 远端脚本在生成阶段将临时目录展开为安全字面量，避免 `set -u` 下引用未定义的 shell 变量。

## 验证标准

- 64 MiB/64 MiB swap 的模拟数据能进入低内存分支并排除 cron。
- OOM 退出会立即显示明确的内存不足信息，锁冲突仍可重试。
- systemd 与非 systemd 的包列表正确，安装脚本通过 shell 语法检查。
- 正常节点部署、中断按钮和既有前端脚本回归通过。

## 进度

- [x] 确认 OOM 根因
- [x] 修改低内存安装流程
- [x] 完成候选版本测试
- [x] 备份并部署生产版本
- [x] 修复并验证 `remote_stage` 变量回归
- [x] 根据新日志定位 `Preconfiguring packages ...` 峰值并完成下载/dpkg 方案

## 风险

- 平台 cgroup 的 64 MiB swap 上限无法在容器内扩容；优化能显著降低安装峰值，但极端镜像或仓库依赖仍可能超过 128 MiB 总额度。
- 新方案仍需管理员在真实 64 MiB 节点上重试一次才能确认该镜像的全部依赖可以在额度内完成 dpkg 配置。
- 不在排查过程中手工安装软件或把节点加入面板，需由管理员修复上线后重新点击部署。
