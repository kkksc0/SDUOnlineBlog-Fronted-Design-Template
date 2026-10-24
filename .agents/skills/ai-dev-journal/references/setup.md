# 安装、启停与迁移

## Agent 执行的一句话安装流程

1. 确定用户正在工作的项目绝对路径。若当前目录就是完整模板，直接使用；否则将 README 指定仓库下载或克隆到临时目录，读取其 README 和本文件。只复制本 skill 的运行资源，不覆盖目标项目业务文件。无需个人全局技能安装器。
2. 保持完整 skill 目录。Windows x64 执行 `<来源SkillRoot>/bin/windows-x64/journal.exe doctor`，成功后执行 `install --project <目标项目绝对路径>`。安装到项目本身时也可重复执行，已有口令、授权状态和日志保持不变。
3. macOS/Linux 先确认已有 Python 3.12+，执行 `python3 <来源SkillRoot>/scripts/bootstrap.py --project <目标项目绝对路径>`。它只用标准库引导，在目标 skill 的 `.venv` 中准备 pip/cryptography，不修改系统解释器。缺少 Python、venv/pip 或网络时报告具体缺项并保持未启用；不要安装全局依赖。
4. 读取 install 返回的 notice 文件并向用户展示，等待确认。此时 status= pending，不能写日志；安装请求本身不算确认。若已明确拒绝，执行 disable 或维持 pending。
5. 用户确认后，使用**目标项目内**的入口执行 `enable --project <项目绝对路径> --confirm`。该命令验证环境、口令和已有密文，向 AGENTS.md/CLAUDE.md 合并托管区块，最后写入本机启用状态。参数不能替代实际用户确认。
6. 显式读取合并后的项目规则，运行 status 验证 enabled=true，说明记录已启用及停用口令。不要写虚构测试对话；下一条实际项目请求应产生 request/result。新会话从项目内启动，实际验证宿主会读取规则。

安装不等于启用；init 仍可创建空白本地口令配置用于旧式手动接入，但不会授权记录。安装器使用 assets/course-config.json 中的**课程共享口令**初始化新项目，已有本地配置保留，不覆盖或自动轮换。已存在但无效/空白的配置需在本机修复后再启用。不要把安装本模板的请求理解为向所有其他项目安装。

## 统一命令

Windows 入口是 `<SkillRoot>/bin/windows-x64/journal.exe`。源码安装后用 `<SkillRoot>/.venv/bin/python <SkillRoot>/scripts/journal.py` 替代（Windows 源码开发的虚拟环境解释器在 Scripts/python.exe）。所有项目参数为绝对路径。

| 命令 | 用途 |
| --- | --- |
| doctor | 环境和加密自检，不读取项目配置 |
| install --project ROOT | 复制运行资源、创建本地配置和待确认状态；不记录 |
| status --project ROOT | 查看状态、确认是否需要告知；不输出口令或日志正文 |
| enable --project ROOT --confirm | 仅在首次或新版告知获得真实确认后启用 |
| enable --project ROOT | 恢复已有相同告知版本的授权，历史原样保留 |
| disable --project ROOT | 立即停用，保留日志；无需额外确认，也不记该操作 |
| append --project ROOT | stdin 接收 JSON；未启用则拒绝 |
| read --project ROOT [--session UUID] | 解密显示，不生成明文文件；停用后仍可读 |
| verify --project ROOT [--session UUID] | 校验现存密文；events=0 不代表已经记录 |
| pack --project ROOT --output OUTSIDE.zip --logs-only | 验证并只打包 .enc；无日志则拒绝；不含授权、配置、环境文件和依赖 |

停用口令：**停止记录本项目的 AI 开发日志。** 没有 Agent 时可直接运行 disable。停用等待正在发布的单条记录结束，命令成功返回后不会再发布新记录。恢复无须重新输入口令。日志管理操作不递归记录。

旧 pack（不带 --logs-only）为兼容保留，仍是全项目归档，不遵守 .gitignore，不作为作业源码打包方案。--logs-only 输出在项目外、不覆盖旧文件，拒绝日志目录中的链接；项目其他位置的依赖链接不会影响纯日志包。

## 常驻规则与宿主

AGENTS.md 与 CLAUDE.md 使用 `<!-- ai-dev-journal:start -->` / `<!-- ai-dev-journal:end -->` 托管区块；合并保留已有项目规则。重复启用不重复追加。破损/重复标记会拒绝，保留原文件并报告。

- [Codex](https://learn.chatgpt.com/docs/build-skills)：项目 .agents/skills 及 AGENTS.md；指令链在新会话启动时建立，安装当轮需显式读取新规则。
- [Claude Code](https://code.claude.com/docs/en/memory)：CLAUDE.md 使用 @AGENTS.md 导入；项目里已有其他 Claude 规则照常保留。共享核心不复制另一套技能。
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/context/agent-instructions/README.md)：默认项目候选 AGENTS.md/CLAUDE.md；@ 导入并非其语法，但它直接读取 AGENTS.md。关闭指令插件或缺少文件/命令能力时不能保证调用。
- 其他宿主：由当前 Agent 根据实际支持的**项目级**常驻指令入口引用同一 SKILL，不猜测全局配置位置。验收一次真实多轮记录后再称已实测；仅提供文件不等于已适配所有宿主。

## 加密、升级和状态

密文格式保持 v1：每事件随机 16 字节 salt，Scrypt n=32768/r=8/p=1 生成 32 字节密钥；AES-256-GCM 使用 12 字节 nonce，格式版本作为认证附加数据。课程共享口令可逆解密，也允许知晓者重新生成密文，所以不证明真实性或完整性。

新版读取历史 v1 密文；新 facts 字段需要新版读取器，旧程序不保证识别。旧项目没有本机授权状态时一律待确认，已有口令和历史不改。相同告知版本的启用/停用状态在重复安装和升级中保留；告知范围实质变化需新确认。不要用老版本程序绕过启用门禁。

`ai-dev-journal.local.json` 与 `ai-dev-journal.state.local.json` 默认 Git 忽略；本地状态不是防伪授权凭证。安装/启用检测到它们已被跟踪会拒绝。无 Git 时只能写忽略规则，不能证明未跟踪。共享课程口令本身公开在分发资源中，本地配置仍不随日志包发送。

自己的设备迁移可单独传递口令配置，再在新设备确认启用；发给另一个人时不复制授权状态。程序不自动换密或重加密已有历史，也不提供密码找回。

## 故障恢复

先确认 doctor 成功、status enabled=true。普通记录失败同 ID 同输入重试一次，仍失败报告缺口并继续任务；恢复只补可核对事实，不伪造原始时间或历史。

强制退出可能遗留根目录 `.ai-dev-journal.control.lock`、事件 `<event_id>.lock` 空目录或 `.pending-*` 密文临时文件。确认没有运行进程、备份日志后，人工检查并移除对应空锁再重试；不删除已有 .enc。程序普通异常自动清理。控制锁使停用与发布协调，但不是跨设备同步机制。

源码重新构建 Windows 包使用仓库 scripts/build_windows.ps1。构建在独立 .build-journal 环境完成，并更新源码/程序哈希与实际依赖版本，重建后必须跑真实程序测试。
