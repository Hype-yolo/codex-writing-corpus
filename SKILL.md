---
name: codex-writing-corpus
description: 用户要求从自己的本机 Codex 聊天中提取写作样文，或已启用个人语料参考后代写、实质改稿时，增量选择带出处的中文表达候选。仅整理语料、检查来源时不代写；普通问答和纯格式转换不自动取样。
---

# Codex 个人语料参考

本 Skill 负责提取和选择参考，不提供固定文风、不替代用户选择的写作 Skill。适用已安装 Python 3.14+ 的 macOS/Linux；当前脚本依赖 Unix 文件锁，Windows 原生环境尚不支持，可在有日志的 WSL 环境自行验证。

## 范围与启用

用户要求提取本人聊天或启用自动参考时，只扫描当前用户的 Codex 日志。自动参考需要用户明确要求启用；安装文件本身不代表同意改变既有写作流程。首次说明会在本地保存筛选结果，写作时选中的最多三段会进入当前写作模型的上下文。不要声称写作模型因此全程离线。

用户明确指定样文时优先使用，不额外自动检索。普通问答、事实核实、机械排版不取样。不得擅自编辑全局 AGENTS.md 或其他 Skill；用户要求接入某个写作入口时，只修改对应入口并保留其余规则。

## 运行

脚本相对于本 SKILL.md 为 `scripts/codex_corpus.py`。先解析本文件的真实路径（包括符号链接），以其父目录作为实际安装目录，使用可用的 Python 3.14+，不要假定某个人的用户名或 Homebrew 路径。缺少所需运行环境时如实说明，不悄悄跳过压缩日志。

仅提取：`python3 <本Skill目录>/scripts/codex_corpus.py refresh`

写作前选择：`python3 <本Skill目录>/scripts/codex_corpus.py select --query-stdin --genre '本次文体、受众、目的' --limit 3 --format json`

将主题和目的经 stdin 传入，不必发送整篇私人稿件。默认扫描 `$CODEX_HOME`，未设置时为 `~/.codex`；覆盖 sessions 与 archived_sessions。默认数据写入该目录下的 writing-corpus。可用 `--codex-home` 和 `--output-dir` 显式指定其他位置；修改输入路径不会自动改变已声明的输出路径。

每次 select 会增量刷新。知道当前会话ID时加 `--exclude-session-id` 排除。一次稿件的起草与复核复用同一组选样，不逐步重新搜索。结果为空或失败时按当前材料继续，不能声称匹配过历史文风。

## 归属和使用

只有 `reference_eligible=true` 且 tier 为 confirmed 或 auto_high_confidence 的样本可以作为自动参考。confirmed 对应 authorship.status=human_confirmed；auto_high_confidence 对应 inferred_not_verified。后者只是程序推断，不等于本人原创认证。

返回后仍检查媒介、表达目的与作者归属：纯操作命令、明显引用、敏感私人内容、与文章风格不适配的片段就跳过，不为凑三段补入待确认内容。当前检索是字词匹配，不保证找到最适合的风格例子。

选中的样文交给当前写作方法使用。本入口只负责数据来源与归属，不另外规定句式、情绪、布局或结束方式。

记录样本ID、归属和原日志出处，正文仅在本轮写作需要时使用。不给外部服务发送整库；不把模型写出的新稿自动升级为本人语料。用户喜欢一篇AI稿也不等于其本人创作。

只有用户逐条确认作者身份，才可写 accept；用户指出不是本人写的，可写 reject。具体文件、判据、隐私和迁移限制见 [references/data-and-limits.md](references/data-and-limits.md)。

## 与现有写作方法配合

用户明确要求将本地样文交给 write-like-me 或其他写作 Skill 时，作为该次用户指定的参考来源传递。应明确说明这是用户授权的本地适配，不能冒称官方原版已经具备这一行为。保持其他写作规则，不引入另一套禁用词或自动文风评分。效果由用户对新话题盲评验证，不能承诺加入语料必然更像本人。

通用 write-like-me 接入文件在 [integrations/write-like-me/SKILL.md](integrations/write-like-me/SKILL.md)。用户要求接入时，让实际写作入口引用或链接该文件，使用对应安装目录的 CLI。私人开发与公开发布分仓维护，发布同步保留来源版本，不公开私人配置或开发材料。
