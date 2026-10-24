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
