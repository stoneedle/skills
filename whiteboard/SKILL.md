---
name: whiteboard
description: 委托 Gemini 探索或推演系统，为用户形成可讲述的理解，并按需生成临时 HTML 架构图。
---

# 架构白板

为用户建立可讲述的系统心智模型。Gemini 主导探索、综合和表达；你负责提供上下文、核验关键事实、纠错和展示。

## 生成候选理解

1. 读取 [references/understanding.md](references/understanding.md) 作为面向用户的理解偏好，读取 [references/visuals.md](references/visuals.md) 作为可选图示规则。
2. 将用户原话、当前问题、工作区绝对路径、两份参考内容和 [references/result.schema.json](references/result.schema.json) 交给 Gemini。无论是理解现有实现、讨论新设计、基于现状重构还是解释变化，都使用同一套理解规则。
3. 按 [`agy`](../agy/SKILL.md) 调用 `Invoke-Agy.ps1`，通过 `-JsonSchemaPath` 要求结构化结果。同一 Codex 任务内的同一问题脉络复用返回的 `conversation_id`；目标或工作区变化时开启新会话。

Gemini 返回：

- `user_text`：可直接交给用户的完整理解，是唯一内容源。
- `visualization`：可选 HTML 图示，只能可视化 `user_text` 已表达的关系，不增加新的事实或判断。
- `verification.claims`：供你核验的关键现状断言和源码依据，不面向用户。

## 核验与纠错

只核验会改变用户心智模型的事实：核心职责、调用或流转方向、关键交接语义，以及现状与提案是否混淆。依据必须能从文件路径、符号和调用关系真正支撑断言；设计判断本身不要求现有符号。

发现明确事实错误时，将核实后的正确事实及源码依据一次性交回原 Gemini 会话，让它重新综合 `user_text`，并在需要时同步更新 HTML。每次用户交互最多首次调用一次、自动返工一次。

返工后仍有明确事实错误时，不再调用 Gemini。你只修正受影响的 `user_text` 句子；若图中也表达了该错误，同步修正对应节点或连线。保持其余表达和布局不变。

完成条件：最终文字中的关键事实成立；图示若存在，与最终文字一致且没有新增结论。

## 交付

将最终 `user_text` 直接回复给用户，不附加核验过程、工作清单或第二份总结。

仅当 `visualization.needed=true` 时，将完整 HTML 写入 `%TEMP%/whiteboard-<topic>-<timestamp>.html`，并使用 Windows `Start-Process` 打开。`needed=false` 时不创建空白文件。
