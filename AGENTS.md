# 项目级开发日志

这些约定只用于本项目及其子目录，不向个人或全局配置写入任何设置。

## 入口与作用范围

- 以本 AGENTS.md 所在目录作为 ProjectRoot。编码前，加载 ProjectRoot/.agents/skills/ai-dev-journal/SKILL.md。
- SkillRoot 是上述 SKILL.md 的父目录，与终端当前目录无关。参考文件和工具都先与 SkillRoot 拼接并解析为实际绝对路径，不照抄尖括号占位符。
- Windows x64 使用 SkillRoot/bin/windows-x64/journal.exe，通过宿主已有的终端/命令执行能力调用。不要寻找一个名叫 append_event 的原生工具。
- 新会话先执行 doctor。保持整个 bin 目录，不能只复制 exe；其他系统按 skill 中的源码要求处理，不尝试执行 Windows 程序。

## 编码任务

- 本项目根目录存在 ai-dev-journal.local.json 时，按 skill 的事件格式记录用户指令、AI 理解、实际修改、纠正、失败和实际验证结果。
- 不读取或输出配置中的密码；由程序读取。仓库内仅有空白模板，实际密码由使用者在本机配置，不提交 GitHub。
- 编码前写 request，重要进展写 progress/correction，每轮交付前追加 result；同一任务与同一轮保持对应 ID，不编造历史或验证。
- 通过 stdin 传 UTF-8 JSON，不把用户原文拼成命令执行，不在项目中创建明文日志临时文件。
- 日常不额外播报记录动作；重试一次仍失败则简短说明。记录器自己的动作不重复生成日志事件。
- 仅记录本项目，不扫描、初始化或写入其他独立项目。用户要求查看日志时再解密展示，不自动生成复盘评价。

## 配置与验证

不要将空白模板误认为已经配置密码。实际配置就位且 doctor 成功后再使用 append/read/verify；没有实际配置时说明需要在本机配置，不自动填入固定口令。不得绕过 init 对已跟踪密码配置的防误传检查。
