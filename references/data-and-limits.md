# 数据与限制

## 本地文件

默认位于 `$CODEX_HOME/writing-corpus`（未设置CODEX_HOME时是 `~/.codex/writing-corpus`）：

- 候选语料.jsonl：confirmed 与 auto_high_confidence 候选，是否实际适用仍看reference_eligible。
- 待确认片段.jsonl：review/rejected/excluded，不自动作为写作样文。
- 可读语料.md：最多40段预览，完整数据在JSONL。
- 统计.json：索引覆盖、消息与片段数。
- 语料索引.sqlite3：出处、增量游标、必要用户片段、助手与工具文本的指纹。
- decisions.json：用户对特定片段的作者确认或拒绝，由用户表达决定后维护。
- external-sources.json：用户显式启用的外部已审阅语料快照及其 SHA-256；不存在时只使用 Codex 候选。

所有这些是接收者运行后生成的私人文件，不属于公开发布内容。默认0600权限；不要将生成目录公开或同步到公共仓库。

## 接入已审阅的微信语料

`select` 读取数据目录下的 `external-sources.json`，不会自行发现其他文件：

```json
{"schema_version":1,"sources":[{"name":"my-reviewed-chat","enabled":true,"path":"reviewed-chat.jsonl","sha256":"替换为已审阅整个JSONL文件的64位SHA-256"}]}
```

path 可为绝对路径或相对 manifest 的路径。显式 `enabled:false` 不加载；启用项缺少有效路径、哈希或名称会失败。快照内容变化后，先重新审阅变化，再更新哈希，不能用重新计算哈希代替审阅。

快照每行是一个样本对象，必须包含 `id`、`text`、`tier:"auto_high_confidence"`、`authorship:{"status":"inferred_not_verified"}`、`reference_eligible:true`、`review:{"status":"accepted","method":"agent_review","reason":"本段审阅依据"}` 和非空 `sources`。模型审阅应筛掉复制转发、他人文本与归属不明内容；只有保留项进入该快照，审阅记录与原始资料仍留在私人目录。accepted 表示本次审阅允许参考，不等于用户本人逐条确认原创。

每个微信 source 包含 `kind:"wechat"`、原始本地 JSONL 的绝对 `path`、正整数 `line`、真实 `conversation_id` 和非空 `timestamp`；可增加精选文件的 `curated_path` 和 `curated_line`。不把微信会话写成 Codex session_id。脚本验证这些字段结构与快照哈希，不会据此证明原作者身份，也不自动重新解析或审阅原始微信记录。

加载后每个微信 source 附带该条记录的 authorship、review、record_id 和 reviewed_snapshot（快照名称、文件、行、哈希），完整信息保留在候选和已选原始样本中供验证、审计。正式写作上下文只带引用正文、真实出处和归属状态，不带审阅理由、归属判断依据或快照审计元数据。正文相同的 Codex/微信样本只出现一次，全部出处保留；某个 Codex 出处已本人确认，不会将另一个微信出处的模型推断升级为本人确认。用户已拒绝的相同正文不因外部快照重新入池。

select 的统计原有字段仍是 Codex 库存；`external_sources_enabled`、`external_samples_loaded` 是本次外部加载数，`external_samples_rejected_by_user_decision` 是被已有本人拒绝决定排除的外部条数，`merged_unique_candidates_before_limit` 和 `duplicate_references_merged` 是合并后的候选数及去重数。refresh 仍只刷新 Codex 索引，不把外部文本复制入其数据库。

## 筛选能力

读取canonical用户消息，排除子代理会话、已知环境/规则注入、结构化问卷、重复事件记录。引用、疑似粘贴、代码和长文进入待确认；用已有助手/工具输出的指纹检查回贴。助手与工具正文不写入索引。常见凭据和明显敏感片段用占位符替代，不输出其原文。

role=user不代表作者是本人。外部AI回贴、短片段复制、转述和改写可能漏检；隐私规则也不是无遗漏检测。当前适配中文，自动候选主要为80–600字、至少40汉字的第一人称或有推理的表达；它不会自动纳入所有中文消息，也不适合宣称为通用多语言原创认证器。输入方式无法区分键入、语音或听写。

## 纠正归属

在数据目录的decisions.json中写入完整片段ID，例如：

```json
{"decisions":{"替换为实际片段ID":{"decision":"reject","note":"用户指出这是转贴"}}}
```

accept仅用于用户明确确认该段是本人创作。禁止模型根据像不像自行确认。刷新/选择会重新读决定，不需重扫原始文件。敏感或不适用文本不会仅因accept而解除所有限制。

## 增量与重建

首次扫描全部日志，随后仅处理变化文件；压缩档变化会重新读。锁防止同一输出目录同时写入。日志正常追加受支持；外部原地修改中段且首尾未变可能漏检。改变提取规则、敏感规则或任意编辑旧日志后，需要新输出目录全量重建，再保留原decisions。当前没有自动规则版本迁移。

只有本机已有的日志可被读取；云端独有、已删除或权限不可读的聊天不在范围内。日志格式将来变化可能需要升级脚本。没有后台常驻任务；自动来自写作前调用select。未调用时不会持续扫描。

脚本没有联网或模型训练。合格候选交给选样模型、选中的样文交给写作模型后，会遵循那个模型及宿主的实际数据路径，不能称整个写作流程完全离线。
