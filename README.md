# AI 开发日志 · 项目模板

为前端作业及其他项目记录可核对的 AI 协作过程。核心 skill 位于 `.agents/skills/ai-dev-journal/`，只安装到当前项目；首次告知并确认后启用，教师可用课程统一口令解密。

## 一句话安装

把下面一句话发给具备项目文件读写、命令执行能力的 Agent：

> 请按照 https://github.com/kkksc0/SDUOnlineBlog-Fronted-Design-Template 的安装说明，为当前项目安装 AI 开发日志；先说明记录范围、用途和解密方式，等我确认后启用。

Agent 按 [安装流程](.agents/skills/ai-dev-journal/references/setup.md)准备环境，展示[首次告知](.agents/skills/ai-dev-journal/references/notice.md)，等待你确认后启用。普通安装请求不等于同意记录，不收集启用前历史。若下载的版本还没有 install/enable 命令，应获取本版本完整分发包，不能套用旧命令声称安装成功。

## 一句话停用、恢复和查看

- **停用口令：停止记录本项目的 AI 开发日志。** 也接受“暂停日志”等同义指令；停止写入并保留历史，不要求再次确认。
- **恢复：恢复本项目的 AI 开发日志。** 已确认相同告知范围时直接恢复。
- **查看：查看本项目的 AI 开发日志。** 解密显示可能进入宿主聊天历史。
- **提交：为教师打包本项目的加密日志。** 使用 `pack --logs-only`，仅打包已验证的密文，不夹带配置、环境文件或依赖。

如需不经 Agent 直接停用，在项目根目录执行：

```powershell
& '.\.agents\skills\ai-dev-journal\bin\windows-x64\journal.exe' disable --project (Get-Location).Path
```

macOS/Linux 使用 `.agents/skills/ai-dev-journal/.venv/bin/python` 调用同目录 `scripts/journal.py`，参数相同。

## 记录内容与用途

启用后，本项目的需求讨论、解释、计划、编码、调试和反馈每轮先写 request，结束写 result。重要失败和纠正追加记录。用户可见原话、Agent 理解、实际操作及检查证据分别保存；用户陈述、工具结果和文件证据明确区分。

这些材料供教师判断学习过程。作品完成、测试通过或用户说“懂了”都不直接等于独立完成或掌握知识；记录器不自动评分或贴能力标签。日志管理操作不递归记录。写入失败重试一次仍失败会提示记录缺口并继续任务；宿主禁止写入时遵守限制并说明未记录。

## 加密是可逆的

日志在 `docs/engineering/ai-worklog/`，每条为 `.enc` 文件。沿用 Scrypt 与 AES-256-GCM，可用 `read` 解密、`verify` 检查密文。课程统一口令来自 skill 的 `assets/course-config.json`，它是课程共享配置，并非空白模板或私人秘密；安装程序复制到本机 `ai-dev-journal.local.json`，不在回复中回显。

任何掌握课程口令的人都能解密拿到的日志。这不提供同学之间的保密，也不证明内容没有漏记、删除或改写。记录器不自动上传；宿主自身可能保存对话和工具历史。已有项目的口令始终保留，不自动换密或重加密。

授权状态另存于 `ai-dev-journal.state.local.json`，不提交或随日志分享。仅存在密码文件不会启用；旧安装升级后也需首次告知确认。复制项目到新使用者时不复制本机授权状态，不能替对方同意。

## 兼容范围

| 环境 | 接入方式 |
| --- | --- |
| Codex | 项目 `.agents/skills` 与根目录 AGENTS.md |
| Claude Code | CLAUDE.md 通过 `@AGENTS.md` 导入共同规则，不要求全局安装 |
| DeepSeek Harness | 默认项目指令入口读取 AGENTS.md；宿主需启用指令和文件工具 |
| 其他 Agent | 将核心 SKILL 接入其实际支持的项目指令入口，并验证实际调用；不声称自动兼容所有宿主 |
| Windows x64 | 包内程序及 `_internal/`，无需 Python |
| macOS/Linux | 已有 Python 3.12+ 时，bootstrap 自动建立项目内虚拟环境和依赖；缺少 Python 时提示，不安装系统 Python |

常驻规则只能规定默认行为，不是强制监听器。安装后当前 Agent 显式读取规则；下次从项目内启动会话。脚本测试、宿主多轮验证和未验证项目分别列在[验证记录](.agents/skills/ai-dev-journal/references/validation.md)。

完整包必须保留 skill 的 assets、references、scripts 和运行库。具体命令、故障处理、事件字段见[接入说明](.agents/skills/ai-dev-journal/references/setup.md)与[事件格式](.agents/skills/ai-dev-journal/references/events.md)。
