# 安装、配置与迁移

## Windows 64 位：免安装运行

当前 ZIP 已包含 `bin/windows-x64/journal.exe` 及同目录 `_internal/` 运行库。完整解压即可在 Windows x64 使用，不用安装 Python、加密依赖，也不需要联网下载运行环境。不要只复制 exe；保持整个 skill 文件夹结构。

每次新会话先让 AI 使用包内入口检查：

```text
<skill目录>/bin/windows-x64/journal.exe doctor
```

返回 ready=true 即可继续。之后所有命令都使用这一个入口；项目配置与原有 `.enc` 格式不变。程序内有中文错误说明，不会静默退回明文。

这是命令行记录器，由 AI 调用，不是双击后显示窗口的日志阅读软件。包缺失或损坏时重新解压完整 ZIP，不自动下载安装其他程序，不修改系统 Python，不要求管理员权限。

此免安装包只适用于 Windows x64。macOS、Linux、Windows ARM 原生版尚未打包；这些平台仍使用源码方式，不声称开箱即用。

## 其他平台或源码开发

源码入口需要 Python 3.12+，以及 requirements.txt 中的 cryptography；仅源码用户需要安装依赖。没有 Context7 可用，因此实现依据为官方文档：
- [Scrypt](https://cryptography.io/en/latest/hazmat/primitives/key-derivation-functions/#scrypt)
- [AES-GCM](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM)

加密格式固定为 v1：Scrypt n=32768/r=8/p=1、32 字节密钥、每事件随机 16 字节盐；AES-256-GCM、12 字节随机 nonce；格式版本作为认证附加数据。盐和 nonce 无需保密。认证用于发现被修改的单条密文，不承诺完整历史不可删改。

## 安装 skill

保留整个 ai-dev-journal 文件夹，不只复制 SKILL.md。Windows x64 使用包内程序，无需安装依赖；其他平台源码方式才执行：

```text
python -m pip install -r <skill目录>/requirements.txt
```

- Codex：复制到个人技能目录 `~/.agents/skills/ai-dev-journal/`。可参考 [官方 skill 文档](https://developers.openai.com/codex/skills/)。
- Claude Code：复制到 `~/.claude/skills/ai-dev-journal/`，参见 [官方 skills 文档](https://code.claude.com/docs/en/skills)。
- DeepSeek Harness：让实际安装版本通过其 skill 加载入口载入本目录，并在项目常驻指令中加入下面规则。其扩展入口仍在演进，不假定 `.claude/skills` 会被自动扫描；必须实际确认 skill 已列出、规则已加载。参见 [官方仓库](https://github.com/deepseek-ai/deepseek-harness)。

不声称已经在以上三个宿主中完成真实会话测试。脚本可用不等于宿主自动触发已验证。

## 每个项目初始化一次

```text
<skill目录>/bin/windows-x64/journal.exe init --project <项目绝对路径>
```

若已经持有自己的密码配置，先将它放进业务项目根目录，再运行 init；已有配置不会被覆盖，不需要重复输入密码。不要复制别人的配置。以下命令以 Windows 入口为例，源码用户替换为 `python <skill目录>/scripts/journal.py`，参数相同。

初始化会向 .gitignore 追加规则，保留既有内容。尚无配置时才创建密码留空的 `ai-dev-journal.local.json`，由你在本地编辑器填写：

```json
{"version": 1, "password": "在本机填入你自己的长口令"}
```

不使用本说明中的示例文字当作真实口令；不要把真实口令发给 AI。脚本拒绝空密码与样例密码。配置只保存版本和口令，日志格式参数固定，不可通过配置降低强度。

若配置已被 Git 跟踪，添加忽略也不能撤回跟踪或历史：先处理仓库中的泄露并更换口令。Git 可用时，脚本检测到已跟踪的标准名称配置会拒绝初始化；没有 Git 时仅添加忽略规则，不能证明未跟踪。更换密码不会自动重加密旧日志；第一版不提供轮换，旧配置需保留以读取旧日志，勿直接替换。

项目规则（合并进 Codex 的 AGENTS.md、Claude Code 的 CLAUDE.md，以及 Harness 当前版本支持的常驻项目指令，别覆盖原内容）：

```markdown
## 开发过程日志
若项目根目录存在 ai-dev-journal.local.json，所有编码任务使用 ai-dev-journal skill。
先加载该 skill 的 SKILL.md，按规则记录用户指令、重要修改与每轮结果；任务开始即写 request，交付前追加 result。
不要在普通回复中额外播报日志操作，不读取或输出密码配置；让写入脚本自行读取。
Windows x64 直接调用 skill 内 bin/windows-x64/journal.exe，不要求额外安装 Python 或依赖。
每次新会话先执行 doctor 进行环境自检。
不记录记录器自身动作；不自动复盘。失败重试一次仍失败时简短报告。
```

安装后重开会话，验证普通编码请求能实际触发记录。宿主强制要求宣布 skill 使用时优先遵守宿主规则，不能保证隐藏所有工具操作。

## 自己的设备之间传输

复制项目（包含密文日志），并通过你信任的渠道单独复制同一份 `ai-dev-journal.local.json` 到新设备项目根目录。新设备安装完整 skill 并加载项目规则；Windows x64 直接用包内程序，不再安装 Python 或依赖。没有配置也可重新创建并填同一口令；无需找回私钥。切换设备的 skill 包和项目规则仍须存在，不能只复制日志。

本机配置是明文保存的口令。项目内的 AI、程序及有文件读取权限的人技术上可以读取它，skill 的“不读取”规则不是访问控制。备份要包含口令，发给其他人的包必须排除口令。

若系统在写入时强制退出，可能遗留 `<event_id>.lock` 空目录或 `.pending-*` 密文临时文件。脚本不会自动删除锁。确认没有写入进程后，先备份日志目录，再人工检查并移除对应空锁后复用原事件 ID 重试；不得删除已有 `.enc`。普通异常会自动清理。verify 只检查已经发布的 `.enc` 文件，不把尚未发布的临时文件算成成功记录。

## 查看和检查

```text
<skill目录>/bin/windows-x64/journal.exe read --project <项目路径>
<skill目录>/bin/windows-x64/journal.exe read --project <项目路径> --session <UUID>
<skill目录>/bin/windows-x64/journal.exe verify --project <项目路径>
```

read 解密后只输出终端，不写明文文件；如在 AI 工具中执行，正文可能进入该工具的历史记录。verify 只报告通过数量，不展示正文。

## 对外分享

```text
<skill目录>/bin/windows-x64/journal.exe pack --project <项目路径> --output <项目外的新ZIP路径>
```

pack 不区分大小写地排除所有同名本地密码配置及 .git 文件/目录，保留加密日志；遇到符号链接或 Windows junction 拒绝打包，避免带入外部文件。输出不得在项目内，不覆盖既有文件。此命令不是通用秘密扫描器，不处理项目自身其他密钥。

Windows 或其他压缩软件直接压缩文件夹不会遵守 .gitignore。对外 pack 包不能自动解密，自己的设备应另行传配置。未加密旧日志、编辑器备份、对话记录和已提交的密码不会被本工具自动清理。
