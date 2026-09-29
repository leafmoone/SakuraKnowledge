# MEMORY.md

## 项目概况

- SakuraKnowledge 是独立的离线证据保全知识快照核心，Python 要求见 `pyproject.toml`；无模型、GPU、ORM、服务或 Pool 依赖。
- 长期状态以 README、`docs/` 和 `reports/P1/` 的可核验证据为准；阶段性审查状态不在此固化。

## 项目文件地图

- `src/sakura_knowledge/`：核心模型、存储、API、CLI、适配器和安全边界。
- `tests/`：单元与硬化测试；`tools/`：审计、摄入和测量工具。
- `docs/architecture.md`、`docs/data-contract.md`、`docs/source-adapters.md`：架构、数据契约和来源边界。
- `reports/P1/P1_REPORT.md` 及相邻 JSON：构建、验证、来源审计和评测证据。
- `skills/sakura-knowledge/SKILL.md`：独立 Skill 说明；`pyproject.toml`：安装元数据与 `sknow` 入口。

## 项目长期习惯

- 修改前先检查 `git status` 并保留已有工作；提交时显式 `git add` 目标文件，禁止用 `git add -A` 掩盖无关变化。
- 每次涉及发布或审查的 `dev` 提交都正常 push，然后用 `git ls-remote origin refs/heads/dev` 核对本地 HEAD；不 amend、rebase、reset 或 force-push。
- 真实来源验证优先使用冻结、哈希绑定、只读输入和机器可读 receipt；fixture、候选映射和推断结果不得替代真实来源证据。
- Windows 非 ASCII CLI 输出必须显式使用并记录 UTF-8 环境；失败、歧义、`NOT_RUN` 和知识缺口保持原状，不为通过审查改名。

## 项目长期记忆

- 身份边界是 `(kind, namespace, value)`；`IDENTITY_TRUSTED` 只接受 `source_backed`，`TEXT_TRUSTED` 才允许 `generated_from_evidence` 支持描述/FTS。
- `local.tag_aggregate` 不等于 `danbooru.tag`；标题、相同拼写、confidence、candidate 或单向/双向候选都不能产生 verified `entity_tag`。
- Moegirl 的 raw attributes、subject categories、CV names、gender 保持来源字段；不得自动转换为 Danbooru tag、`character_of` 或 Bangumi person join。
- 快照必须在完整性、外键、FTS、ledger、输入 digest 和 source-account 检查后原子发布，且不得覆盖已有输出。
- Pi runtime、SakuraPool 整合和完整人工事实审查必须有实际执行证据；静态文件、测试或报告文字本身不算完成。

## 隐性细节/坑点

- 当前数据与审查报告中的远端、分支、快照和 wheel 状态都可能变化；引用时附最后确认日期和具体 receipt，不把易变状态当长期事实。
- `build/` 是构建产物目录并被忽略；源输入只读，任何新快照使用新输出目录。
- `sknow` 的 Windows 非 ASCII JSON 可能受系统代码页影响；命令退出码、stderr 和 `PYTHONIOENCODING=utf-8` 必须一起保存。
- 评测必须记录实际读取代码 SHA、snapshot/manifest binding、命令和退出码；报告修订不能改变既有 case 数值而不说明。
