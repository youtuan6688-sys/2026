# HappyCode Agent Team

多角色 AI 团队，由 CEO（主会话）调度，Worker（子进程）执行任务。

## 架构

```
team/
  config.yaml          # 团队配置：角色定义、任务流、优先级
  dispatch.sh          # 派任务给角色（前台/后台）
  dashboard.sh         # 任务看板（全局/按角色筛选）
  review.sh            # CEO 验收任务（通过/打回）
  orchestrate.sh       # 复杂编排（并行/流水线/依赖管理）
  plans/               # 编排计划文件（YAML）
  roles/               # 角色定义和工作区
    ceo/CLAUDE.md          # CEO 调度指南
    backend/               # 后端工程师
      CLAUDE.md            # 角色指令
      workspace/           # 任务日志、结果、产出
    frontend/              # 前端工程师
    reviewer/              # 代码审查员
    pm/                    # 产品经理
    researcher/            # 研究员
    devops/                # DevOps 工程师
    qa/                    # QA 测试工程师
    cmo/                   # 营销总监
    cfo/                   # 财务总监
  shared/
    conventions.md         # 所有角色共享的规范
    skills/                # 共享技能库（可复用模式）
  tasks/
    queue/                 # 待分配
    active/                # 执行中
    review/                # 待验收
    done/                  # 已完成
    failed/                # 失败
```

## 工作流

1. **CEO 收到需求** -> 拆解任务
2. **派发**: `./dispatch.sh <role> <task_id> "描述" [优先级] [--bg]`
3. **Worker 执行**: 读指令 -> 写日志 -> 做任务 -> 写结果
4. **CEO 验收**: `./review.sh <task_id> [approve|reject]`
5. **归档**: 任务移入 done/，经验沉淀到 vault/memory/

## 复杂任务编排

```bash
# 并行执行
./orchestrate.sh parallel plans/example-feature.yaml

# 流水线（按依赖顺序）
./orchestrate.sh pipeline plans/example-feature.yaml
```

计划文件支持 `depends` 字段，自动管理依赖关系。

## 角色一览

| 角色 | 职责 | 模型 | 预算 |
|------|------|------|------|
| CEO | 任务分配、验收、闭环 | claude-opus-4-6 | - |
| backend | Python/API/数据库 | claude-sonnet-4-6 | $5 |
| frontend | Web UI/交互/样式 | claude-sonnet-4-6 | $5 |
| reviewer | 代码质量/安全审查 | claude-sonnet-4-6 | $3 |
| pm | 需求分析/PRD/验收标准 | claude-sonnet-4-6 | $3 |
| researcher | 技术调研/市场分析 | claude-sonnet-4-6 | $3 |
| devops | 运维/监控/部署 | claude-sonnet-4-6 | $3 |
| qa | 测试策略/自动化测试 | claude-sonnet-4-6 | $3 |
| cmo | 营销策略/内容/增长 | claude-sonnet-4-6 | $3 |
| cfo | 成本核算/预算/财务分析 | claude-sonnet-4-6 | $2 |

## 共享资源

- **知识库**: `vault/` (Obsidian) — 所有角色可读写
- **记忆**: `vault/memory/` — 决策、经验、工具清单
- **技能**: `team/shared/skills/` — 可复用的模式和模板
- **规范**: `team/shared/conventions.md` — 编码/协作规范

## 快速命令

```bash
# 派任务（后台）
./team/dispatch.sh backend fix-api "修复用户认证 API 的 token 过期问题" P1_high --bg

# 查看看板
./team/dashboard.sh

# 查看某角色任务
./team/dashboard.sh backend

# 验收任务
./team/review.sh fix-api approve "代码质量好，测试完整"

# 并行编排
./team/orchestrate.sh parallel team/plans/my-feature.yaml
```
