# 操作踩坑日志

避免重复踩坑，每次遇到问题都记录在这里。

---

## ADB / uiautomator2

### 1. 中文输入方案
- **❌ `adb shell input text`**: 不支持中文
- **❌ `u2.send_keys()`**: 需要 ADBKeyboard IME，安装失败（Android 12 安全限制）
- **❌ `u2.clipboard`**: Android 12 剪贴板权限限制，SecurityException
- **✅ `u2(selector).set_text()`**: 通过 UiAutomator 的 UiObject.setText()，原生支持中文

### 2. uiautomator2 连接断开
- **原因**: 两个 Python 进程同时连接同一台设备，后台任务和前台冲突
- **解决**: 不要并行运行两个 u2.connect()，串行执行
- **预防**: 脚本开头检查是否有其他连接

### 3. set_text 和 EditText 定位
- 优先用 `d(text="placeholder_text")` 定位
- 备选用 `d(className="android.widget.EditText")` — 但如果有多个 EditText 会冲突
- 最可靠: 用 `resourceId` 定位，但小红书的 id 被混淆了 (`0_resource_name_obfuscated`)

---

## Gemini App

### 4. Gemini 模式切换
- **坑**: 新建对话后可能默认"快速"模式而非 Pro
- **解决**: 每次 new_chat 后调用 `_ensure_pro_mode()`，检查按钮文字
- **流程**: 点击模式按钮 → 弹出菜单 → 选 "Pro"

### 5. Gemini 大图查看界面卡住
- **坑**: 下载图片后，如果不点返回就直接操作，会找不到输入框
- **解决**: new_chat 前检查是否有"返回"按钮，先 press("back")
- **相关代码**: gemini_image.py 的 new_chat() 方法

### 6. Gemini 图片下载等待
- **坑**: "下载图片"点击后会显示"正在下载完整尺寸的图片..."，需要等几秒
- **解决**: 下载后 sleep(8) 再查找新文件
- **图片位置**: `/sdcard/Pictures/{timestamp}.png`

---

## 小红书 App

### 7. 发布按钮选择器
- **坑**: 小红书 resource-id 全部被混淆为 `0_resource_name_obfuscated`
- **解决**: 用 `content-desc` 或 `text` 定位
  - 底部导航: `d(description="发布")`
  - 标题框: `d(text="添加标题")`
  - 正文框: `d(text="添加正文或发语音")`
  - 发布按钮: `d(text="发布笔记")`
  - 草稿按钮: `d(text="存草稿")`

### 8. 发布流程有多个"下一步"
- 第一个"下一步": 相册预览 → 图片编辑（滤镜/贴纸）
- 第二个"下一步": 图片编辑 → 文案编辑
- **别漏了第二个**

### 9. 返回操作的弹窗
- 在编辑页按返回会弹出: "确认保存笔记至草稿箱吗？" → 确定/取消
- 草稿编辑页返回可能弹出: "不保存" 选项
- **处理**: 每次 press("back") 后检查是否有弹窗

### 10. 相册图片排序
- 最新的图片在左上角 (index=0)
- 3列网格，每格约 354x354 像素
- 坐标计算: x = 177 + col*363, y = 554 + row*363

---

## DeepSeek App

### 11. DeepSeek 发送按钮
- **坑**: 发送按钮 `content-desc="发送"` 但 `clickable=false`
- **解决**: 用坐标点击，中心 (966, 1474)
- **备选**: 查找 bounds 后计算中心点

### 12. DeepSeek 回复读取
- 通过 dump_hierarchy() 获取所有 TextView
- 过滤条件: `len(text) > 15` 的 TextView 节点
- 回复可能分成多个 TextView 节点，需要拼接

---

## 通用

### 13. 截屏文件名
- 用时间戳避免覆盖: `f"{name}_{int(time.time())}.png"`
- 临时截屏放 /tmp/
- 正式截屏放 logs/screenshots/

### 14. 操作间隔
- App 切换后: sleep(3-4)
- 点击后: sleep(1-2)
- 输入后: sleep(0.5)
- 等待生成: 轮询每 5 秒检查一次
- 不要用固定间隔，自动化脚本加 random.uniform()
