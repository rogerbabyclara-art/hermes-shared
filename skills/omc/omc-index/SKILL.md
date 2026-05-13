---
name: omc
description: Oh My ClaudeCode - Multi-agent orchestration for Hermes (OMC port)
version: 1.0.0
author: OMC/Hermes
metadata:
  from_omc: true
  category: orchestration
---

# OMC (Oh My ClaudeCode)

OMC 多智能体编排系统已移植到 Hermes。

## 可用的 OMC 技能

### 执行模式 (Execution Modes)
- `$autopilot` 全自动端到端开发
- `$team` N个协调智能体并行工作
- `$ralph` 持久执行直到完成验证
- `$ultrawork` 最大并行执行

### 规划技能 (Planning)
- `$plan` 战略规划
- `$deep-interview` 苏格拉底式需求澄清
- `$ralplan` 迭代规划共识

### 其他工具
- `$learner` 从会话提取可复用模式
- `$skill` 管理技能
- `$cancel` 取消当前模式

## 快速开始

```
$autopilot build a REST API for task management
```

```
$team 3 "fix all TypeScript errors"
```

```
$ralph refactor the auth module
```

## OMC 来源

- GitHub: https://github.com/Yeachan-Heo/oh-my-claudecode
- Hermes 技能路径: ~/.hermes/skills/omc/
