# 事件格式 v1

所有事件：`event_id`、`session_id`、`task_id`、`turn_id` 为 UUID；`kind` 为 request/progress/correction/result，`tool` 为 codex/claude-code/deepseek-harness/other，`data` 为对象。`recorded_at` 由脚本生成，采用带时区的 UTC ISO 时间；跨设备阅读按时间及事件 ID 排序，时间受设备时钟影响。

data 内只允许下面字段，避免把未知内容误当系统元数据。字段均可省略；request 必须有非空 user_text。result 必须有 status。

| 字段 | 类型 / 含义 |
|---|---|
| user_text | 字符串，指令原文或明确标注无法获得原文 |
| understanding | 字符串，AI 理解 |
| assumptions | 字符串数组，未经确认的假设 |
| changes | 字符串数组，实际修改及文件 |
| decisions | 字符串数组，关键方案选择摘要 |
| failures | 字符串数组，失败尝试和实际错误 |
| checks | 对象数组；每项 name、status、evidence，status 为 passed/failed/not_run |
| user_feedback | 字符串，实际用户反馈 |
| open_items | 字符串数组，剩余工作、未验证、缺失信息 |
| redactions | 字符串数组，脱敏说明 |
| related_event_ids | UUID 数组，纠正/关联旧记录 |
| facts | 可选事实数组，每项 actor、summary、source、reference，见下文 |
| status | in_progress/completed/blocked/cancelled；completed 不意味着用户验收 |

示例（仅说明格式，不是实际开发记录）：

```json
{
  "event_id": "90000000-0000-4000-8000-000000000001",
  "session_id": "90000000-0000-4000-8000-000000000002",
  "task_id": "90000000-0000-4000-8000-000000000003",
  "turn_id": "90000000-0000-4000-8000-000000000004",
  "kind": "request",
  "tool": "codex",
  "data": {
    "user_text": "把登录页的错误提示改清楚，先别改接口。",
    "understanding": "调整登录页提示文案，保留现有接口行为。",
    "assumptions": [],
    "status": "in_progress"
  }
}
```

重试同一事件时必须保留原输入。新的用户纠正是新事件，不覆盖原指令。记录本轮结束但任务未完成时，result.status 仍为 in_progress。未收到用户验收时，可在 checks 添加 name=用户验收、status=not_run。

## 结构化事实（v2 读取器新增，密文容器仍为 v1）

每项恰有四个非空字符串字段：

- `actor`：user / agent / unknown。无法核对是谁完成的工作用 unknown。
- `summary`：可核对的事实，不写能力、态度或分数。
- `source`：user_statement / tool_result / artifact，分别为用户陈述、工具结果、文件证据。artifact 必须指实际文件；准备发送的回答不是文件证据。
- `reference`：实际可见消息的定位/短引文、命令与结果定位，或项目相对文件路径与行号；相关事件可引用 event_id。不虚构消息编号。

Agent 在 result 中可用 changes/decisions 记录“已准备的回复摘要”，不能在最终回复发送前称已送达；用户是否收到或验收只依据可见反馈。facts 聚焦业务或学习任务的证据，日志命令成功本身不是学习事实。

```json
{
  "facts": [
    {"actor": "user", "summary": "用户说懂了", "source": "user_statement", "reference": "本轮用户消息：懂了"},
    {"actor": "agent", "summary": "Agent 修正自己先前写错的选择器", "source": "artifact", "reference": "src/main.js:12"},
    {"actor": "unknown", "summary": "测试命令无法启动，作品未验证", "source": "tool_result", "reference": "npm test 退出码 127，缺少命令"}
  ]
}
```

## 公正记录场景

| 场景 | 应保存的事实与边界 |
| --- | --- |
| 用户指出 Agent 方案错误 | 保留用户纠正，Agent 的旧方案和更正各有事件；错误不转嫁给用户 |
| 用户说自己完成或理解了 | 记录为用户陈述，没有工具/文件证据就不写已独立完成或已掌握 |
| Agent 完成代码并测试通过 | 工作归 Agent，检查只表示具体测试通过，用户掌握情况未知 |
| 环境/测试工具不可用 | 写工具失败或未运行，不能判定作品错误或用户不会 |
| 仅讨论、解释，没有改代码 | request/result 仍配对，明确未改代码、未运行不适用检查 |
| 压缩后看不到原文 | user_text 明确标注只剩摘要；不补写伪造引文 |
| 用户粘贴来源不明的代码 | 记录提供代码的事实；其作者和独立完成程度未知 |
| 日志失败后补记 | 新事件注明补记与可见证据范围，不伪造当时的 recorded_at |

结构校验能约束字段和来源类型，不能判断语义是否真实；须结合具体行为场景验收，不声称自动保证公正或完整。新读取器兼容旧事件，旧读取器可能不认识 facts。
