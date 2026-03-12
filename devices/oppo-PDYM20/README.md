# OPPO PDYM20 自动化项目

## 设备信息
- **型号**: OPPO PDYM20
- **序列号**: EUVW6TOJN7D6IFZ5
- **系统**: Android 12 (ColorOS F.43)
- **连接**: USB (adb)

## 目录结构
```
oppo-PDYM20/
├── README.md       # 本文件
├── CHANGELOG.md    # 任务日志
├── scripts/        # 自动化脚本
├── config/         # 配置文件
└── logs/           # 运行日志
```

## ADB 快速命令
```bash
adb devices                          # 检查连接
adb shell pm list packages -3        # 第三方App列表
adb shell input tap X Y              # 点击屏幕坐标
adb shell input text "hello"         # 输入文字
adb shell am start -n package/activity  # 启动App
adb shell screencap -p /sdcard/s.png && adb pull /sdcard/s.png  # 截屏
```
