# 团队共享规范

## 通用规则（所有角色必须遵守）

### 语言
- 所有日志、报告、注释用中文
- 代码中的变量名、函数名用英文
- commit message 用英文

### 代码风格
- Python: PEP 8, type hints, 函数 < 50 行
- JavaScript/TypeScript: ESLint + Prettier
- 文件 < 800 行，超过则拆分
- 不可变数据优先，避免 mutation

### 文件操作
- 优先编辑现有文件，不创建多余文件
- 所有输出写文件，不要只输出到终端
- 工作产物放在自己的 workspace/ 目录

### 任务协议
1. 开始前：读取任务文件，理解需求
2. 执行中：实时写工作日志到 workspace/
3. 完成后：写结果文件，更新任务状态为 review
4. 遇到阻塞：写入任务文件说明原因，等待 CEO 协调

### 知识库使用
- Obsidian vault 在 ~/Happycode2026/vault/
- 记忆文件在 vault/memory/
- 有用的发现写入 vault/memory/learnings.md
- 技术方案写入 vault/memory/decisions.md

### 安全规则
- 绝不硬编码密钥
- 使用环境变量或 .env
- 不提交敏感文件
- 所有用户输入需验证
