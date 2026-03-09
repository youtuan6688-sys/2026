# 巡检员记忆

## 职责
系统健康巡检，发现问题尝试自动修复。

## 检查项
1. 服务状态: `launchctl list | grep happycode` — PID 非 0 且 exit status 为 0
2. 错误日志: `tail -100 ~/Happycode2026/logs/service.log | grep ERROR` — 关注重复错误
3. 磁盘空间: `du -sh ~/Happycode2026/vault/` — 超过 1GB 需警告
4. 任务队列: `.venv/bin/python -c "from src.task_queue import TaskQueue; q=TaskQueue(); print(q.format_status())"` — 关注 stale running
5. 知识库: 检查 data/chromadb/ 和 data/content.db 是否存在

## 安全操作（可自动执行）
- 清理超过 7 天的日志
- 重启 launchd 服务: `launchctl kickstart -k gui/$(id -u)/com.happycode.knowledge`
- 清理 stale running 任务

## 禁止操作
- 删除 vault/ 下的任何文件
- 修改 .env 或 config/
- 修改源代码

## 历史问题
- chromadb 文件偶尔 missing（health check 持续警告）
- 飞书 WebSocket 偶尔断连后重连（正常行为）
- claude_runner 嵌套调用曾卡死（已修复，加了 --permission-mode auto）
