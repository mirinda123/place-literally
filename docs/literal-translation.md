# 使用 Codex CLI 批量生成字面含义

脚本：`backend/translate_meanings.py`。Prompt：`backend/prompts/literal_meanings.txt`。
从当前配置的 `ES_INDEX`（默认 `features-v10`）读取名称，通过本机已登录的 Codex CLI 生成翻译；不需要 API Key。历史索引保留供回退。
需要较新版本的 Codex CLI（支持 `exec --output-schema --ignore-user-config --ephemeral`）。
先运行 `codex login status` 检查登录。调用消耗所用 Codex 登录账户的额度。

以下 PowerShell 命令在 `D:\Projects\literal-name-map` 执行。

## 第一期：国家、五种语言

默认类型为 `country`，默认语言为 `zh,en,ja,fr,es`，默认模型为 `gpt-6.1-sol`，推理强度为 `xhigh`。模型说明见 [OpenAI 官方文档](https://developers.openai.com/api/docs/models/gpt-6.1-sol)。
先预览选中了多少地点、不调用模型也不写入 ES：

```powershell
backend\.venv\Scripts\python.exe -m backend.translate_meanings --dry-run
```

先生成三个地点的草稿：

```powershell
backend\.venv\Scripts\python.exe -m backend.translate_meanings --limit 3
```

生成全部国家草稿（串行执行，可能需要较长时间）：

```powershell
backend\.venv\Scripts\python.exe -m backend.translate_meanings --kind country --languages zh,en,ja,fr,es
```

结果位于 `work/literal-translations/cache/*.json`，每个文件包含模型请求输入、结果、生成时间和 `verified: false`。
每次运行的 `runs/<时间>/plan.json`、`prompt.txt`、`report.json` 记录任务计划、Prompt 和进度。
草稿中的 `ready` 只代表模型给出了完整答案并通过结构检查，不代表已由资料核实。

确认草稿内容后，以相同筛选参数加 `--apply` 写入 ES。注意草稿会重新给出所有选定语言的释义，也可能修正已有译文：

```powershell
backend\.venv\Scripts\python.exe -m backend.translate_meanings --kind country --languages zh,en,ja,fr,es --apply
```

`--apply` 会复用匹配的缓存；如果有尚未生成的地点，也会调用 Codex。因此只想写入试跑的三个地点时，要保留 `--limit 3`，或用 `--feature-id` 精确选择。
只写入 `ready` 的结果，并在写入前保存完整原文档到当次运行的 `backups/`。
默认只挑出选定语言中仍有缺失释义的地点，但 Codex 会核对并重新给出该地点所有选定语言的释义。已有译文是待核对线索，可以被修正；未选定语言、名称、坐标和 OSM 标识保持不变。
如果已有译文发生修正，旧 `meaning_id` 会清空，避免沿用可能错误的语义分组；报告会列出 `corrected_languages` 和需复核的分组。不自动生成新的 `meaning_id`。
对于已经具备所有选定语言释义的地点，使用 `--review-existing` 才会重新核对。
写入前重新读取 ES，检查原名、名称和释义是否变化，并使用 ES 序列号避免覆盖并发修改。
前端刷新后可读取新释义。v2 到 v3 的 IK 分词迁移可执行 `python -m backend.reindex_ik`；旧索引会保留。

## 参数

| 参数 | 默认值 / 作用 |
| --- | --- |
| `--kind` | `country`；可选 `city`、`town`、`settlement`（city/town/metropolis）、`state`（state/province）、`selected`（仅指定 ID，可跨类型） |
| `--languages` | `zh,en,ja,fr,es`；逗号分隔语言标签，最多 20 个 |
| `--model` | 精确模型 ID，默认 `gpt-6.1-sol` |
| `--reasoning-effort` | 默认 `xhigh`；其他可用强度取决于所选模型 |
| `--feature-id` | 指定 ES 的 feature_id，可重复传入；仍受 kind 筛选 |
| `--feature-id-file` | JSON 格式的 feature_id 数组；`--kind selected` 时必须指定 ID |
| `--guidance-file` | 可选的批次专用核实规则，连同通用 Prompt 保存到运行目录并参与缓存键 |
| `--review-existing` | 同时复核所有选定语言已有释义的地点；默认只处理有缺失的地点 |
| `--limit` | 最多处理多少个地点，按 feature_id 排序；省略时全部 |
| `--delay` | 两次调用之间至少 3 秒；仅串行，无并发 |
| `--timeout` | 单次 CLI 调用最多 180 秒 |
| `--retries` | 每个地点最多重试 2 次，带退避；可设为 0 |
| `--max-errors` | 累计 3 个地点失败后停止，防止登录或模型配置错误时不停调用 |
| `--output-dir` | `work/literal-translations`；任务报告、缓存和写入备份目录 |
| `--codex-bin` | `codex`；可指定 codex.exe 的绝对路径 |
| `--dry-run` | 只预览，不调用模型或写入 ES |
| `--apply` | 将完整结果写入 ES；默认只保存草稿 |

指定模型、语言和城镇类型的示例（替换模型占位符为账户可用的模型 ID）：

```powershell
backend\.venv\Scripts\python.exe -m backend.translate_meanings --kind settlement --languages zh,en --model YOUR_MODEL_ID --limit 10
```

CLI 在临时目录以仅可写该工作区的沙箱运行，允许使用工具和实时网页搜索；Prompt 经标准输入传入，输出受 JSON Schema 约束。
临时目录之外的项目文件仍不由 Codex 调用修改，ES 仅由脚本在指定 `--apply` 时写入。
为避免项目指令和插件影响翻译，调用不加载用户 config.toml；认证仍使用本机 Codex 登录。
因此用户配置里的默认模型、第三方 provider 等不会自动继承；脚本明确传入模型和推理强度。

## Prompt 的取舍

先确定解释哪个原名，再把同一含义翻成多种语言。已有 `literal_name` 指定分析的名称；已有释义只供核对，不视为权威，必要时可据查证结果修正；
否则选择 OSM 当前主要名称的当地拼写，必须原样对应输入名称，不能凭空创造原词。
例如“中国”的字面意思与英文外名 China 的来源不同，不能混用。
沿有资料支持的命名链追溯到更早的词义：地名借自人名、姓氏、旧地名、民族或河流时，不止步于“以某某命名”；但也不能把“来自某某”或普通地名翻译当成字面含义。
圣人或人名成分有资料支持时，保留“圣＋规范人名”等直接含义，以及地理或描述性修饰词；同一人名在同一种目标语言中使用一致、通行的译名。有可靠依据时保留人物称号，不确定具体人物时在英文 `note` 说明，不猜测身份。更深的人名词源写入 `note`，不替代直接含义。不能仅凭 `San`、`Saint` 等拼写前缀断定名称来自圣人。
Prompt 为常见人名给出统一的简体中文译法，例如 John→约翰、Joseph→约瑟夫、Charles→查尔斯、Ferdinand→斐迪南；这些写法也用于带地理修饰词的长释义。
没有 `literal_name` 时，以 `names.und` 所代表的当前主要地名为目标，选用当地使用且语言可确认的已有拼写。不能仅因较古老或原住民名称有现成词源就替换主要地名；相关名称可在英文 `note` 中说明，只有能解释主要地名来源时才追溯。
主要拼写可以与相应语言字段的完整形式不同，例如 `names.und = St. Gallen` 与 `names.de = Sankt Gallen`；确认前者的语言后可保留主要拼写。其他语言的外名仍不能错误标为该语言。
生成输入包含地点坐标和已有外部标识，用于区分不同国家或地区的同名城市；它们也参与草稿缓存和写入前的变更检查。
既有向量不会发送给释义模型，也不参与草稿缓存和文本变更判断。写入备份会显式读取并保留原向量；新释义写入后需要重新生成对应向量。
如果有可靠的组合含义（例如“某人的岛”），专名自身的更深词根不明也可以保留专名；不必因此把整个地名判为 `uncertain`。
若词义来自更早的同名对象，各语言释义应简短标明这种间接关系，避免误以为它描述了当前地点；`note` 说明追溯链和资料来源。
保留方向、颜色、修饰词；不把“南方的都城”简化为“都城”，不把 New York 归为 New City。

不要求长篇词源分析；可使用工具和实时网页搜索核对名称与含义，查询过的外部资料 URL 写入草稿 `note`，不编造引文。允许简短总结明确且常见的来源；争议、民间附会、
有充分资料支持但仍非定论的释义，把不确定性写在 `note`，译文只保留含义本身。若资料支持多种不同词义，`literal_meanings` 按释义列出最多三项，每项包含所有目标语言，例如 `[{"translations":{"zh":"勇猛者之国","en":"land of the brave"}},{"translations":{"zh":"持矛者之国","en":"land of the spear bearers"}}]`。同一词根的近义改写或造成该含义的不同原因不算不同候选。例如词根均指“明亮”，只是可能描述无树或焚林后的山谷，应合并为一个词义，在 `note` 解释所指对象。`ready` 表示有可供编辑的候选译文，不表示词源已成定论。
前端一个释义显示一行，多个释义显示编号列表；ES 将每项作为 nested 文档检索。无法确定原名、仅能确定名称转用，或找不到有可靠资料支持的词义时，返回 `uncertain` 和空列表，保存在报告/缓存中，不写入 ES。
字面含义能用短语说清就用短语；需要补足限定条件时允许一两句，单语种不超过 300 字符，不写成长段。
模型知识和自动检查仍可能出错，大批量公开前建议抽查。

## 中断和重试

2026-10-01 本地 Saint/San 城市复核：按主要英文／默认名称的独立前缀筛选，兼容 Saint-/San- 和明确的 St. 别名，仅处理 `kind=city` 的 115 个地点；没有扩大到另外 80 个城镇。使用 `gpt-6.1-sol / xhigh` 生成 118 条五语种释义，复核统一 29 处人名译法，再以 `qwen3.7-text-embedding` 生成并写入 590 个 512 维 `document` 向量。完整原数据、向量和任务报告保存在 `work/saint-san-20261001/`，其余 13,766 个地点经源文档哈希检查未变化。

本地接口验证：Saint John（加拿大）与 San Juan（波多黎各）在英文、中文的词语模式中互相匹配，向量模式的双向余弦分数均为 1.0000。向量模式仍会把一些不同人名关联起来，例如英文 Saint John 与 Saint Paul 的余弦分数约 0.744，高于现有 0.60 阈值。释义标准化不能把通用向量相似度变成人物身份判断；这次没有改动关联算法或阈值。

重复同一命令会复用已完成草稿，失败项重新调用。缓存按输入名称、既有释义、目标语言、
指定模型、推理强度和 Prompt 内容区分；修改这些内容会生成新任务。默认模式下，所选语言均有释义的地点下次自动跳过。
`uncertain` 也是已完成结果，不会反复请求；想重试时可换 `--model`、修改 Prompt，或使用新的 `--output-dir`。
运行报告和缓存均记录指定模型及推理强度。旧的未指定模型的试跑缓存不会复用到新配置。

一次运行存在失败项时退出码为 1，详情在 `report.json`。CLI 错误先检查登录状态、模型权限、
网络和额度；ES 写入错误检查映射字段上限与报告。脚本不会自动提升 ES 字段上限或删除索引。

Codex 结构化脚本调用参考：[OpenAI 官方文档](https://developers.openai.com/blog/eval-skills)。
