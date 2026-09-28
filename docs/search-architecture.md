# 当前搜索架构：单一 features-v10

当前范围是地名字面含义地图。应用只查询 Elasticsearch 的 features-v10 索引；每个地点一个文档，七个业务字段：feature_id、kind、names、location、literal_name、literal_meanings、meaning_id，以及可选 external_ids.osm（keyword 数组）。旧索引（含 v4）保留作回退。

没有独立词源分析索引、语义目录索引、PostgreSQL 或向量数据库。字面含义的多语言翻译放在同一文档中，literal_name 标明正在解释哪个具体名称。没有释义时允许空值。

Python 提供名称/含义搜索、实体详情、同义实体查询。中文名称使用配置的 CJK 分析器；nested 的 literal_meanings.translations.zh 使用 analysis-ik 的 ik_max_word 建索引、ik_smart 查询；英文含义使用不删除停用词的 English 分析器，日文含义使用 Kuromoji，其他语言沿用 standard。完整名称使用规范化 keyword 子字段。概念与主题匹配使用版本化 data/meaning-groups.json，最终候选仍由 ES 查询返回。v3 到 v4 可执行 `python -m backend.reindex_v4`；v4 到 v5 执行 `python -m backend.reindex_search_v5`；v5 到 v6 执行 `python -m backend.reindex_search_v6`；v6 到 v7 执行 `python -m backend.reindex_search_v7`；v7 到 v8 执行 `python -m backend.reindex_search_v8`，仅复制已有文档并更新查询专用分析器，不重新采集或翻译数据。v8 到 v9 执行 `python -m backend.reindex_embeddings_v9`，去掉误命名的空向量字段，改用 qwen3.7-text-embedding 字段。v9 到 v10 执行 `python -m backend.reindex_search_v10`，复制全文档和向量并更新查询专用停用词；v9 保留供回退。

批量导入全球城市后，名称通过 `copy_to` 汇总到内部 `search_names`（配置的 CJK 分析器，附规范化 `.raw` 子字段），检索不再展开 `names.*`。这是倒排索引辅助字段，不改变业务文档 `_source`。名称全文检索使用短语匹配，完整名称使用 `.raw`。地图使用 `/api/map-features` 游标分页读取轻量字段，完整多语言名称保留在详情与关联接口。

前端使用 feature_id 对应地图坐标、搜索命中和字面含义卡片。点击任何有字面含义的地点时，前端仍调用 `/api/features/{feature_id}/similar?lang=zh`，其中 `lang` 是界面语言；没有任何释义的地点不发请求。后端按原始释义的列表项分别构造 ES nested 查询，对已提供的中、英、日、法、西释义分别用查询专用分析器执行 `match`（`operator=OR`、`minimum_should_match="2<-50%"`）。分词后不超过两个词须全部命中；更多词允许缺少一半（向下取整）；只剩一个词时 ES 最多要求命中一个。同一条候选释义至少命中其中两种语言才返回：ES 外层 `bool.minimum_should_match=2` 执行语言门槛，每种语言用 `constant_score` 记一票，响应中的 `score` 就是支持语言数。不同候选释义不能拼票，不同源释义也不会拼成一个含义；仅有一种翻译的源释义不会生成查询。当前界面语言没有翻译时，若该源释义仍有至少两种受支持语言，也可以查询；界面语言只影响显示。v10 的五语查询分析器按 `backend/stopwords/similar_*.txt` 过滤泛用国家称谓、城市类别词、土地词及「地方／place／場所／lieu／lugar」；日文在 Kuromoji 链后增加专用停用词过滤。v10 还过滤英语 by/beside/near、法语 au/aux、西语 al/junto 等位置连接词，保留「河／川／river／río」等实义词。词表建索引时嵌入 ES 设置，修改文本文件不会自动改变正在使用的索引。普通搜索仍使用原来的字段分析器。所有地点类型参与同一次检索，并排除所选地点；不以 meaning_id 加分，也不使用 Python 相对最高分门槛。PIT 与 search_after 取回全部命中结果及最佳的源／候选释义序号；响应中的 `threshold` 暂保留为 null 以兼容客户端。侧栏展示全部结果，地图用浅蓝色虚线地表弧线连接它们；河流、湖泊等类型使用代表点。`/api/features/{feature_id}/related` 仍提供基于 meaning_id 的严格同义兼容接口，但点选地点不再用它生成关联列表。首页含义分类和普通搜索保持原有逻辑。多语言投票会减少单语偶然命中，但诸如“都城／capital”等各语言共同的泛用词仍可能产生宽泛关联，需要结合真实地点继续评估。

数据和 CLI/API 说明见 [backend/README.md](../backend/README.md)。旧 TypeScript 搜索路由、示例搜索和 embedding 适配代码已删除。data/seed.json 仅保留为历史来源资料，不参与运行时读取。

features-v10 的每条 nested `literal_meanings` 释义中已预留 `embeddings_qwen3_7_text_embedding_512_v1`，其 `zh`、`en`、`ja`、`fr`、`es` 分别是 512 维、cosine 的 `dense_vector` 字段。718 个有字面释义的地点共有 990 条释义、4,938 个向量，已覆盖全部现有译文；另有 4 条旧示例释义缺少日／法／西译文，故相应的 12 个语言位置没有向量。补齐脚本和记录见 [向量说明](embedding-pilot.md)。前端默认「文本」继续使用 `/similar`；切到试验性的「向量」后调用 `/api/features/{feature_id}/vector-similar?lang=zh&min_similarity=0.60`。源地点的每条当前语言释义分别生成 `text_type=query` 向量，ES 用 nested `script_score` 精确计算同语言余弦，`min_score=1+min_similarity`，PIT 与 `search_after` 取回全部过门槛地点，再按地点保留最高得分与源／命中释义序号。接口不返回 512 维数组；源地点缺少当前语言向量时返回 `available=false`，不会回退文本搜索。前端滑杆可在 0.50–0.90 调整门槛并显示每个结果的原始余弦分数，高分仍需人工核实。覆盖扩大后仍需重新评估精确搜索延迟，再考虑近似 kNN。已有托管版本不随本地改动更新；部署新版需要可访问的 Python 后端及百炼密钥。

底图 place 标签点击通过提供方专属 ID 解码得到 node/way/relation 标识，调用 /api/features/resolve，精确查询 external_ids.osm。无匹配和身份冲突分别展示状态，服务异常可重试；不使用模糊名称匹配。现有示例的映射也存入 ES，锚点 JSON 不再决定运行时关联。
