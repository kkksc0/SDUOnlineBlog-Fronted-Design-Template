# SDUOnlineBlog Fronted Design Template

在单个项目内使用的 AI 开发日志模板。完整 skill 与 Windows x64 运行工具位于本仓库 `.agents/skills/ai-dev-journal/`，不需要安装到个人全局 skill 目录。

## 目录

```text
项目根目录/
├── .agents/
│   └── skills/
│       └── ai-dev-journal/
│           ├── SKILL.md
│           ├── bin/windows-x64/journal.exe
│           ├── bin/windows-x64/_internal/
│           ├── scripts/
│           ├── references/
│           └── 其余完整文件
├── ai-dev-journal.example.json
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

将业务代码放入本项目，或者把模板中的 `.agents`、配置和项目指令合并进你的项目。合并已有项目时保留原有 AGENTS.md / CLAUDE.md 内容，不直接覆盖。

## 密码配置说明

仓库提供空白配置模板 `ai-dev-journal.example.json`。首次使用时复制为项目根目录的 `ai-dev-journal.local.json`，再在本机编辑器中填写自己的密码。实际配置已加入 .gitignore，不提交 GitHub。

没有配置或密码为空时，不会写入加密日志。自己的设备之间迁移时，单独传输实际配置，或者重新填入相同口令。不要在产生日志后直接换密码，当前工具不会自动重加密已有日志。

任何人取得密码后都能解密使用同一密码加密的日志。Git 忽略不能影响普通压缩软件，也不能撤回已经提交的密码历史。

## Windows x64 开始使用

1. 下载或克隆本仓库，保持 `.agents/skills/ai-dev-journal/` 的完整结构，特别是 `_internal/`。
2. 复制空白配置模板为 `ai-dev-journal.local.json` 并在本机填入密码。
3. 从本项目根目录开启 Codex 或 DeepSeek Harness 会话。项目指令要求编码任务使用本地 skill，日志保存在本项目中，不修改全局配置。
4. 先让 AI 检查包内程序，再开始编码。Windows x64 已自带运行环境，无需安装 Python 或加密依赖。

在项目根目录打开 PowerShell，可直接执行：

```powershell
$ProjectRoot = (Get-Location).Path
$Journal = Join-Path $ProjectRoot '.agents\skills\ai-dev-journal\bin\windows-x64\journal.exe'
& $Journal doctor
if ($LASTEXITCODE -ne 0) { throw '日志工具自检失败' }
```

实际配置就位且 doctor 成功后即可使用 append/read/verify。init 可用于给尚未配置的新项目创建空配置和忽略规则；当密码配置已被 Git 跟踪时，它会按防误传设计拒绝运行。

## 给 AI 的使用要求

让 AI 读取本项目的 AGENTS.md，然后加载 `.agents/skills/ai-dev-journal/SKILL.md`，遵循指令记录本次开发过程。所有工具和参考文件路径都以实际 skill 目录解析，不能把文档中的 `<skill绝对路径>` 原样执行，也不能假定加密程序是一个已注册的独立 MCP 工具。

Claude Code 可通过本项目 CLAUDE.md 读取同一套项目规则和 skill；无需向个人目录安装一份。

## 查看日志

```powershell
$ProjectRoot = (Get-Location).Path
$Journal = Join-Path $ProjectRoot '.agents\skills\ai-dev-journal\bin\windows-x64\journal.exe'
& $Journal verify --project $ProjectRoot
& $Journal read --project $ProjectRoot
```

日志写入 `docs/engineering/ai-worklog/`，每条记录为 `.enc` 密文。read 显示解密内容，不另外生成明文日志文件；在 AI 工具中显示的正文可能保留在聊天历史中。

## 使用范围与验证边界

- 规则和 skill 放在本仓库内，从本项目根目录启动会话；本仓库的子目录也属于使用范围。不要把规则放在多个独立项目的共同父目录。
- 当前免安装运行工具仅适用于 Windows x64。其他操作系统使用源码时仍需 Python 3.12+ 与 requirements.txt 中的依赖。
- skill 需要宿主允许读取项目文件和执行命令；上传附件不等于已解压安装。
- 命令运行成功不等于每轮自动调用已验收。先做一次小修改，确认新增记录，再投入正式使用。
- 工具来自已验证的 v1.1 Windows 分发包。没有放入发送者的业务代码、实际开发日志或构建临时目录。

更多字段、加密格式和测试边界见 `.agents/skills/ai-dev-journal/references/`。运行库的第三方许可通知保留在包内。
