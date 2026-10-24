# v2.0 验证记录

日期：2026-10-24。此记录区分程序测试、宿主实测和未验证项目，不把说明文档当作自动触发证据。

## 程序与分发

| 环境 | 结果 |
| --- | --- |
| Windows，源码 Python 3.13.12 / cryptography 46.0.5 | 34 项：33 通过，1 项真实符号链接测试因权限跳过 |
| Ubuntu WSL，Python 3.12.3 / cryptography 46.0.7 | 34 项：33 通过，1 项 Windows 专用免安装测试跳过；真实符号链接检查通过 |
| Windows x64 新运行包 | PyInstaller 6.22.3，Python 3.13.12，cryptography 46.0.7；doctor 通过，源码与 exe SHA256 匹配 BUILD-INFO.json |
| skill-creator quick_validate | 通过；本地 Markdown 引用均有效 |

回归覆盖：加密读写、篡改/错误口令、并发与去重、原子发布失败恢复、凭据脱敏，以及以下新增行为：

- 首次告知门禁、拒绝/停用、恢复沿用授权、告知版本变化重新确认、损坏状态可以停用。
- 新安装与重复安装；已有口令、授权时间、密文和原项目规则保留；BOM/CRLF 规则合并、损坏托管标记拒绝、写入第二份规则失败时回滚第一份。
- 旧 v1 密文未启用也可读取，新增写入需要确认；Git 已跟踪的本地配置阻止启用。
- facts 字段的主体和来源校验，已有口令与元数据同名时脱敏不破坏固定标识。
- 多轮配对、新会话与明确任务关联、未收尾 request；停用等待在途发布，返回后拒绝后续写入。
- logs-only 包仅包含有效 .enc；排除口令、授权、.env、依赖和临时文件；空日志/损坏日志不生成提交包。
- Windows 完整包移至中文路径，子进程 PATH 为空，PYTHONHOME/PYTHONPATH 指向不存在目录：实际完成安装、待确认、启用、读写、去重、停用/恢复、校验和纯日志打包。

Ubuntu 实际执行 bootstrap，从空项目创建独立 .venv、安装依赖并停在 pending；未修改系统 Python。macOS 没有实机验证。系统没有 Python、离线下载失败等路径有明确错误处理，但未在所有系统逐一实测。

复现程序测试：在 skill 目录运行 `python -B -X utf8 -m unittest discover -s tests -v`。Windows 构建使用仓库 `scripts/build_windows.ps1`，依赖版本位于 `scripts/requirements-build.txt`；构建和旧包备份仅在被忽略的 .build-journal 中。

## Codex 真实宿主验收

在仓库 .build-journal/host-test 独立测试项目执行五个用户轮次，使用本机 Codex CLI 的实际工具能力：

1. 一句话安装：生成 pending 配置、展示告知并等待确认，0 条日志。
2. 明确确认：enabled=true，合并并读取项目规则；管理操作保持 0 条。
3. 只解释 ==/===，禁止改业务文件和运行测试：产生配对 request/result。
4. 新建宿主会话，没有显式提醒记录；用户自述“懂了、另一台电脑做完练习”但未提供代码：自动记录第二组 request/result。原话和事实标为 user_statement；结束记录明确无法核对练习完成情况，没有推导为掌握或独立完成。
5. 一句话停用：disabled，保留 4 条历史，不为停用操作添加事件。

共 2 个日志 session、2 个配对 turn。首轮个别探索命令失败，以及新会话误向 doctor 传 --project、首次 UUID 生成工具不可用等实际失败未删除；宿主自行修正后完成，并在结果中注明自己的操作失败。SKILL 后续明确 doctor 不带 --project，避免同类误用。

## DeepSeek Harness 真实宿主验收

使用本机 `dsh --profile headless`，在独立 .build-journal/dsh-host-test 项目连续执行四个请求；每次 headless 进程重新加载项目上下文：

1. 从本地完整分发包安装，实际状态 pending、0 条记录，展示告知等待确认。
2. 明确确认后启用并加载共同规则，0 条记录。
3. 未显式提醒日志，要求解释 map/forEach 并附带理解自述：产生 request/result，用户自述与实际检查分开记录。
4. 一句话停用后状态 disabled，历史仍为 2 条。

CLI 最终回复与程序回读一致。初测发现把“准备发送的最终回复”误标为 artifact 文件证据；已明确 artifact 必须指实际文件，回答摘要应写入 changes/decisions。使用相同任务在新 headless 进程复测：新 result 把回答表述为“已准备”，facts 仅保留 user_statement，未声称已送达或已验收。原错误记录保留，复测后共 4 条事件、2 个日志 session；验收程序最后恢复停用。

验收没有保存宿主内部推理流，只保留最终回复、状态和退出结果。

## 边界与证据

- Claude Code：共同规则和 @AGENTS.md 导入已实现；本机无可用 Claude CLI，未声称完成真实会话验证。
- 其他 Agent：提供项目级通用接入说明；不声称全部宿主均自动识别。
- 本机副本、受控运行环境和 WSL 验证不等于第二台物理设备或 macOS 实测。
- 常驻规则不强制宿主每轮执行；字段校验不证明语义真实，学习判断仍由教师结合原始证据完成。
- 课程口令可逆解密，不提供同学之间保密或历史不可伪造、不可删除保证。
- 日志测试全部为隔离案例；模板根目录未生成真实本地口令或启用状态，未向其他业务项目或全局安装。

本地详细证据在被 Git 忽略的 .build-journal：acceptance-summary.json、host-phase1–5.jsonl/txt、dsh-phase1–4.txt 和 dsh-lifecycle-results.json、dsh-facts-retest.txt。用于复查测试，不随分发包提交。远程一句话安装以仓库已发布版本为准。
