# Python 后端：features-v10 索引

## 本机反馈

地点详情中的反馈提交到独立的 `place-feedback-v1` 索引，不会自动修改地点释义。用户直接描述问题，无需选择某条释义；提交时保存该地点当前所有释义的翻译快照。昵称为选填项；已有反馈索引会在新反馈提交时自动补上 `nickname` 字段，旧记录保持不变。可在 `backend/.env` 用 `ES_FEEDBACK_INDEX` 设置其他索引名。

查看待处理反馈：

```powershell
backend\.venv\Scripts\python.exe -m backend.list_feedback
```

目前仅供本机试用；公开开放匿名提交前需要增加防滥用措施。

Python 3.11+、FastAPI、Elasticsearch 9.x。当前默认连接 http://localhost:9200 ，使用 features-v10；不创建 etymologies 或 semantic-catalog 索引。

## 启动

在项目根目录执行：

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
backend\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

首次运行先执行 `python -m venv backend\.venv`。配置见 backend/.env.example；复制为 backend/.env 后修改，环境变量优先。ES_INDEX 默认 features-v10，ES_ANALYZER 默认 cjk（用于中文地名与内部名称字段）。`literal_meanings.translations.zh` 使用 IK；英文释义使用保留停用词的 English，日文释义使用 Kuromoji。本机 ES 9.5.4 的 Docker Compose 在 `C:\Users\Admin\Documents\Codex\2026-09-20\wob\outputs\elastic`，镜像 `elastic-local-ik:9.5.4` 已包含 IK，Kuromoji 直接安装在现有 `elasticsearch-local` 容器中。

如果容器被重新创建，Kuromoji 不会随数据卷保留。无需重新构建镜像，在新容器中执行：

```powershell
docker exec elasticsearch-local /usr/share/elasticsearch/bin/elasticsearch-plugin install --batch analysis-kuromoji
docker restart elasticsearch-local
docker exec elasticsearch-local /usr/share/elasticsearch/bin/elasticsearch-plugin list
```

安装版本必须与 ES 一致；重启后列表应同时包含 `analysis-ik` 和 `analysis-kuromoji`。仅 `docker restart` 现有容器不需要重装。从 v3 升级时先运行 `backend\.venv\Scripts\python.exe -m backend.reindex_v4`，再运行 `backend\.venv\Scripts\python.exe -m backend.reindex_search_v5`；如果 v4 已存在，仅运行后一步。v5 复制 v4 的完整文档并验证数量与抽样内容，v4 保留供回退。要回退搜索配置，可将 `ES_INDEX=features-v4` 并使用对应旧版后端代码。已有 v1/v2 数据的旧迁移脚本仍以 v4 为目标，之后需依次复制到 v5、v6、v7 和 v8。空库可以执行 `backend\.venv\Scripts\python.exe -m backend.indexing` 导入 11 条初始示例；切勿在已编辑的正式数据上随意重跑，以免覆盖同 ID 的释义。

`/similar` 使用只在该接口查询中指定的 ES 分析器；停用词源文件位于 `backend/stopwords/similar_*.txt`，建索引时由 `backend/indexing.py` 读入 ES 设置。v8 还过滤「地方／place／場所／lieu／lugar」等泛用地点词，不影响普通搜索的分词。现有 v4 的旧版分析器仍可由 `backend.configure_similar_analyzers` 初始化；不能只修改代码中的停用词就让现有索引使用新版分析器，因此现有索引不会因修改项目中的文本文件而自动更新。
从现有 v8 升级：`backend\.venv\Scripts\python.exe -m backend.reindex_embeddings_v9`。这会新建 features-v9，复制并核对全部文档，仅保留 qwen3.7-text-embedding 的向量字段；v8 保留供回退。

从现有 v9 升级：`backend\.venv\Scripts\python.exe -m backend.reindex_search_v10`。脚本新建 features-v10，完整复制文档与向量并验证数量和分析器；v9 保留供回退。`/similar` 的查询停用词只新增表示位置关系的英语 `by/beside/near`、法语 `au/aux`、西语 `al/junto`，保留「河／川／river／río」等实义词。这样「河边」的连接词本身不会为曼彻斯特和伦敦凑足多语言票数。已有 v10 时脚本不会覆盖，需为再次修改选择新的索引名。

从现有 v7 升级：`backend\.venv\Scripts\python.exe -m backend.reindex_search_v8`。脚本复制全部现有文档并核对五语分词，v7 保留作回退。

从现有 v6 升级：`backend\.venv\Scripts\python.exe -m backend.reindex_search_v7`。脚本复制全部现有文档并核对五语分词，v6 保留作回退。

从现有 v5 升级：`backend\.venv\Scripts\python.exe -m backend.reindex_search_v6`。脚本新建 v6、复制全文档、核对数量及五语分词；v5 保留作回退。修改 `backend/stopwords/similar_*.txt` 后，需要新建下一版索引并切换 `ES_INDEX`，不必重跑 AI 翻译。这里将词表内容写入 ES 索引设置，**不需要复制进 Docker 容器**。如果改用 ES 的 `stopwords_path` 文件模式，文件必须位于每个 ES 节点的 config 目录；仅复制文件不会让正在运行的 `stop` 过滤器热加载，需受控重开索引或重启节点。`_reload_search_analyzers` 的热重载适用于可更新的同义词过滤器，不能假定它会更新普通停用词。

`/similar` 对每条源释义的可用语言分别执行 ES nested `match`（OR）。每种语言用 `minimum_should_match="2<-50%"`：分词后不超过两个词时要求全部命中，更多词时允许缺少一半（向下取整）；仅剩一个词时 ES 最多要求一个。候选的同一条释义仍须至少得到两种语言支持。每种语言由 ES `constant_score` 记一票，响应 `score` 为票数；没有 Python 侧的 55% 分数门槛。此查询参数可直接调整，无需重建索引。

接口文档：http://127.0.0.1:8000/docs 。前端运行 `npm run dev`，访问 http://localhost:5173/。Vite 将 /atlas-api/* 转发到 Python 的 /api/*。

## 索引文档

每个地理实体一条文档，_id = feature_id，七个业务字段和一个可选外部标识字段：

| 字段 | ES 类型 | 说明 |
| --- | --- | --- |
| feature_id | keyword | 稳定实体 ID |
| kind | keyword | city、country、river、lake 等 |
| names | object | 语言代码 → 显示名称 |
| location | geo_point | {lon, lat} |
| literal_name | object | {text, lang}；没有释义时可为 null |
| literal_meanings | nested 列表 | 每个释义为 `{translations:{zh,en,...}}`；无释义时为空列表。各语言按同一列表项对应，最多三个释义 |
| meaning_id | keyword | 同义分组 ID；可为 null |
| external_ids.osm | keyword 数组 | OSM 对象标识，如 node/244081381；默认空数组 |

中文名称按配置的 CJK 分析器索引；`literal_meanings.translations.zh` 使用 IK，英文含义使用保留停用词的 English（仍进行词干提取），日文含义使用 Kuromoji，法语和西班牙语沿用 standard。每个释义作为 nested 文档，含义检索不会跨释义拼接词语。各文本字段的 raw 子字段使用 lowercase + asciifolding normalizer，支持完整名称与转写匹配。这些子字段不增加原始文档的顶层字段。保留英文 `not` 等词只影响分词，不表示搜索已支持否定条件。

`literal_meanings` 中另预留 `embeddings_qwen3_7_text_embedding_512_v1` 对象，包含 `zh`、`en`、`ja`、`fr`、`es` 五个独立的 `dense_vector` 字段；每个字段 512 维、cosine 相似度，属于同一条释义。当前 718 个有字面释义的地点共有 990 条释义、4,938 个向量，覆盖全部现有译文；默认连线继续使用文本检索，切换「向量」后才调用 `/vector-similar`。试跑与全量补齐步骤见 [向量说明](../docs/embedding-pilot.md)。向已有索引添加映射可执行 `backend\.venv\Scripts\python.exe -m backend.add_meaning_embeddings_mapping`；脚本只更新映射，不改动文档。将来写入向量时，翻译更新必须同步重算或清除对应语言的旧向量，避免释义与向量不一致。

名称检索通过 `copy_to` 汇总到内部 `search_names` 字段，使用配置的 CJK 分析器及 `.raw` 子字段，避免同时展开数百种语言字段触发查询子句上限。分词名称使用短语匹配。此字段只存在于索引，不进入原始业务文档或接口结果。导入器负责已有名称的映射迁移与重新索引。

语言字段通过受限路径的 dynamic_templates 建立；导入器校验语言标签、非空文本、坐标范围和重复 ID。新增语言不等于获得该语言专属分词或自动跨语言翻译。初版适合有限语言集合，继续扩展需留意字段数量。

`data/features.json` 是可编辑、可重复导入的数据源。导入按 ID 更新，不会重复插入，也不会删除已经不在文件里的旧记录。导入不是事务，失败后修正并重试；会覆盖同 ID 的 ES 编辑。没有释义的地点仍可按名称找到，不会因为 meaning_id=null 被当成同义。

少量分组配置保存在 `data/meaning-groups.json`，由前端和后端共用，不写入 ES。它服务于首页分类和普通搜索；`/related` 仍按相同 meaning_id 返回严格同义地点。点选任意有释义的地点时，`/similar` 用最多五种语言比较 ES 中对应的字面含义，不要求 meaning_id 或分组配置。原始来源、许可和修改说明保存在 `data/feature-attributions.json`；旧学术型 seed.json 作为历史资料保留。

## 接口

| 请求 | 用途 |
| --- | --- |
| GET /health | 当前索引、分析器、实体数 |
| GET /api/features | 分页读取地点，支持 kind / meaning_id |
| GET /api/map-features | 地图轻量字段，limit ≤ 1000，使用 after 游标继续读取 |
| GET /api/features/resolve?osm=node%2F244081381 | 按 OSM 身份精确关联地点 |
| GET /api/features/{feature_id} | 单个地点及字面含义 |
| GET /api/features/{feature_id}/related | 相同 meaning_id 的其他地点 |
| GET /api/features/{feature_id}/similar?lang=zh | 用已收录的五语释义检索所有地点类型；同一候选释义至少两语支持才返回。lang 表示界面语言，score 为支持语言数 |
| GET /api/features/{feature_id}/vector-similar?lang=zh&min_similarity=0.60 | 仅比较当前语言的释义向量，返回所有达到原始余弦门槛的地点；score 为余弦值，包含源与命中释义序号 |
| GET /api/search?query=新城 | 地名与含义搜索 |
| POST /api/search | 相同能力，JSON 请求体 |

搜索参数：query（1–200 字符）、scope（exact / near / theme）、kind、meaning_id、limit（1–100）、offset（0–9900）。返回 results 中每项包含完整地点字段及 reason、match_kind、score。分页与统计按实体计算。

旧 /api/records、/api/places 和 /api/catalog 已从 Python API 移除。前端已同步使用 feature_id，不再接收 analysis_id。

新城匹配两个地点并排除纽约；南方的都城保留方向限定；主题“新”可包含纽约。否定句明确提示不支持。

向量接口接受 `zh/en/ja/fr/es` 和 0–1 的 `min_similarity`（默认 0.60）。对源地点每条有当前语言向量的释义，使用该语言译文向百炼 `qwen3.7-text-embedding` 请求 `text_type=query` 向量，`instruct` 沿用试跑脚本；查询缓存位于 `work/vector-query-cache`，并发请求会安全复用。密钥仅从后端环境的 `DASHSCOPE_API_KEY` 读取，不能放进前端。ES 在同语言 nested 向量上计算精确余弦，并通过 PIT 与 `search_after` 返回全部过门槛地点；多义词保留最高分的释义对应关系。响应的 `available=false` 表示源地点缺少当前语言向量，不调用模型，也不回退文本结果；`results` 绝不返回向量数组。前端向量模式目前为试验功能，高余弦分数不代表词义关联已核实。随着向量覆盖增加，需重新评估精确搜索延迟。

补齐**全部现有字面释义**的向量：先运行 `backend\.venv\Scripts\python.exe -m backend.embed_all_meanings` 查看待处理数量，再加 `--apply` 调用模型并写入 ES。脚本仅为已有译文生成 `text_type=document` 向量；缺少译文的语言保持空白，已有向量不会被覆盖。使用 `--output-dir work\embedding-all-20260927` 保存 Git 忽略的缓存、运行日志和 `report.json`；中断后以同一目录重跑，可跳过已写入字段并复用成功的模型结果。写入每个地点前会复核译文及 ES 文档版本，避免把旧译文的向量覆盖到新释义上。`report.json` 中的 before／after 数量可核对覆盖率。

无结果返回 200 + 空数组；非法输入 422；不存在的实体 404；ES、模型连接失败或索引缺失 503。前端不回退旧数据。地图通过 search_after 游标分页加载，避免 offset 的 10,000 条限制；每页只返回首期显示语言和地图必要字段，完整多语言名称仍可通过详情接口读取。

## 字面含义翻译

`python -m backend.translate_meanings` 使用本机已登录的 Codex CLI，默认生成国家的 `zh,en,ja,fr,es` 字面含义草稿。
支持类型、语言、模型、限量试跑、缓存续跑、重试和可选 ES 写入；默认筛选有缺失语言的地点，同时核对并可修正所选语言的已有释义。用 `--review-existing` 可复核已完整翻译的地点。
对全部国家（包括已有释义）重新生成并写入：`python -m backend.translate_meanings --kind country --languages zh,en,ja,fr,es --model gpt-6-sol --reasoning-effort high --review-existing --apply --timeout 600`。相同 `--output-dir` 可复用成功草稿继续运行；每个已写入地点在当次 `runs/<时间>/backups/` 有原文档备份。
先用 `--dry-run` 查看计划，使用方法和 Prompt 规则见 [批量翻译说明](../docs/literal-translation.md)。
中国 34 个省级地名批次使用 `--kind selected --feature-id-file` 跨 `state`、`city`、`country` 三种既有地图标签类型，采集和复跑步骤见 [中国省级地名批次](../docs/osm-china-regions.md)。

## 后端测试

```powershell
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
$env:RUN_ES_TESTS='1'
backend\.venv\Scripts\python.exe -m pytest backend/tests -q
```

集成测试使用随机 literal-name-map-test-* 索引，结束时只清理该测试索引，覆盖地点结构、OSM 精确关联及冲突处理、多语言、无释义地点、重复导入、同义边界、分页及错误处理。

## 底图地名关联

点击 OpenFreeMap 的 place 图层地名（国家、城市、城镇、村庄等），前端读取矢量要素 ID，按该提供方 Planetiler 的默认规则解码：原始 OSM ID × 10 + 类型码（node=1、way=2、relation=3）。只对已配置的 openmaptiles/place 数据源应用此规则；其他来源、非安全整数或非 OSM 要素不猜测身份。

`GET /api/features/resolve?osm=node%2F244081381` 对 `external_ids.osm` 做 term 查询。返回 `{osm, status, feature}`：唯一记录 matched；无记录 not_found；多条记录占用同一身份 ambiguous。这三种结果均为 HTTP 200；输入错误 422，ES 故障 503。前端区分未收录、冲突、暂不支持和服务异常，并允许失败重试。连续点击以最后一次为准，不自动按名称猜测。

一个实体可包含多个 OSM ID（比如中心点与边界），但应核对它们确实表示同一地点。导入器校验 ID 格式；ES 不提供数组值唯一约束，查询遇到跨文档冲突会拒绝任选一条。新增 ID 字段采用 put_mapping，无需删除或重建索引。

data/features.json 保留 11 个已核对 OSM 节点的初始地点；当前本地 ES 共 13,800 条，包含 225 个国家名称节点、31 个中国省级地名节点和 13,544 个主要城市、城镇及首府节点。命令与备份机制见 [国家采集](../docs/osm-country-collection.md)、[城市采集与导入](../docs/osm-city-import.md) 和 [中国省级地名](../docs/osm-china-regions.md)。未关联 OSM 的迦太基古城已从 ES 和当前导入文件移除。在线地图按 external_ids.osm 给底图原生标记和地名着色，保留底图的缩放、地点等级筛选和文字避让；不额外绘制全部 ES 地点。点击原生标签继续经过 OSM 查询接口。data/map-anchors.json 仅作为历史坐标校验资料。

换底图提供方或生成规则时必须重新确认 ID 编码。GeoNames 导入需要额外建立 OSM 对应关系；不会自动生成。当前地图分页后仍会加载全部坐标，更大规模应增加视野查询，不能无限全量渲染。
