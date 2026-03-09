# 共享技能: DevOps 模式

## launchd 服务管理
```bash
# 加载服务
launchctl load ~/Library/LaunchAgents/com.happycode.xxx.plist

# 卸载服务
launchctl unload ~/Library/LaunchAgents/com.happycode.xxx.plist

# 查看状态
launchctl list | grep happycode

# plist 模板
cat > ~/Library/LaunchAgents/com.happycode.xxx.plist << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.happycode.xxx</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/script.sh</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/happycode-xxx.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/happycode-xxx.err</string>
</dict>
</plist>
EOF
```

## 健康检查模式
```bash
#!/bin/bash
# 检查进程是否存活
check_process() {
    pgrep -f "$1" > /dev/null 2>&1
}

# 检查端口是否监听
check_port() {
    lsof -i :"$1" > /dev/null 2>&1
}

# 检查最近日志有无错误
check_recent_errors() {
    local log_file="$1"
    local minutes="${2:-5}"
    local threshold="${3:-3}"
    local count=$(find "$log_file" -mmin -"$minutes" -exec grep -c "ERROR\|CRITICAL" {} \; 2>/dev/null || echo 0)
    [ "$count" -lt "$threshold" ]
}
```

## 备份模式
```bash
# 增量备份 vault
backup_vault() {
    local backup_dir="$HOME/backups/vault/$(date +%Y%m%d)"
    rsync -a --delete ~/Happycode2026/vault/ "$backup_dir/"
}
```
