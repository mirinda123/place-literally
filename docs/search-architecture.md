# 当前搜索架构：单一 features-v10

当前范围是地名字面含义地图。应用只查询 Elasticsearch 的 features-v10 索引；每个地点一个文档，七个业务字段：feature_id、kind、names、location、literal_name、literal_meanings、meaning_id，以及可选 external_ids.osm（keyword 数组）。旧索引（含 v4）保留作回退。

没有独立词源分析索引、语义目录索引、PostgreSQL 或向量数据库。字面含义的多语言翻译放在同一文档中，literal_name 标明正在解释哪个具体名称。没有释义时允许空值。

Python 提供名称/含义搜索、实体详情、同义实体查询。中文名称使用配置的 CJK 分析器；nested 的 literal_meanings.translations.zh 使用 analysis-ik 的 ik_max_word 建索引、ik_smart 查询；英文含义使用不删除停用词的 English 分析器，日文含义使用 Kuromoji，其他语言沿用 standard。完整名称使用规范化 keyword 子字段。概念与主题匹配使用版本化 data/meaning-groups.json，最终候选仍由 ES 查询返回。v3 到 v4 可执行 `python -m backend.reindex_v4`；v4 到 v5 执行 `python -m backend.reindex_search_v5`；v5 到 v6 执行 `python -m backend.reindex_search_v6`；v6 到 v7 执行 `python -m backend.reindex_search_v7`；v7 到 v8 执行 `python -m backend.reindex_search_v8`，仅复制已有文档并更新查询专用分析器，不重新采集或翻译数据。v8 到 v9 执行 `python -m backend.reindex_embeddings_v9`，去掉误命名的空向量字段，改用 qwen3.7-text-embedding 字段。v9 到 v10 执行 `python -m backend.reindex_search_v10`，复制全文档和向量并更新查询专用停用词；v9 保留供回退。

批量导入全球城市后，名称通过 `copy_to` 汇总到内部 `search_names`（配置的 CJK 分析器，附规范化 `.raw` 子字段），检索不再展开 `names.*`。这是倒排索引辅助字段，不改变业务文档 `_source`。名称全文检索使用短语匹配，完整名称使用 `.raw`。地图使用 `/api/map-features` 游标分页读取轻量字段，完整多语言名称保留在详情与关联接口。

前端使用 feature_id 对应地图坐标、搜索命中和字面含义卡片。点击有释义的地点时调用 `/api/features/{feature_id}/similar?lang=zh`；`lang` 只决定界面显示，已有的中、英、日、法、西五语释义共同参与判断。

分词关联分为**粗筛**和**细筛**，英文算法注释见 `backend/similar.py`。粗筛使用每种语言的 `similar_<语言>_v3` 分析器，再按 `backend/stopwords/similar_low_information.json` 去除额外介词、冠词和泛用地点称谓，并对词去重。源和目标使用相同规则；原 `.similar` 索引保留分词结果，作为召回超集。每条源释义构造 ES nested 查询：有有效词的语言使用 `terms` 查共有词，没有有效词的语言使用 `.raw` 完整短语。候选的同一条释义至少获得两种语言支持。PIT 与 `search_after` 分页取全候选，不截取 Top N，也不按 BM25 分数筛选。这保证反向独有关系、完整短语关系和两种匹配混合的关系均能进入细筛。

细筛对每一对释义独立判断两个方向：有有效词时，A→B 的门槛按 A 的词数计算，1–2 词须全中，更多词须命中 `ceil(n/2)`；B→A 按 B 的词数独立计算。过滤后没有有效词时，要求两侧完整短语相同，才同时为两个方向各记一票。短语使用现有 `.raw` 的 `name_fold` 规范化，忽略大小写和重音差异，但保留语序、标点和空格；不能把两个空词集合当作相同释义。`In the City` 可以关联相同短语，不会再凭 `in / dans / en` 关联波尔多的沼泽庇护所释义。

分别统计两个方向的支持语言数，任一方向达到两票即返回，`score=max(正向票数,反向票数)`。不同方向不能拼票，不同释义不能拼词或拼票；完整短语与有效词匹配可以在同一对释义的不同语言中共同投票。多条释义逐对比较，每个地点保留最高分的一对；并列按地点 ID 和释义序号固定排序，反向查询只交换两侧释义序号。同一数据版本下，关系和分数对称。进程内缓存分词和短语规范化结果，不预计算地点关系，不调用模型。低信息词表在进程启动时加载，改此表只需重启后端，原释义、已有索引和预处理向量无需修改。

专用 `literal_meanings.translations.<语言>.similar` 多字段由相同分析器建立倒排索引，不改变原全文搜索字段和业务 `_source`。已有 features-v10 需先运行 `python -m backend.configure_similarity_fields` 补建字段和旧文档索引；释义与已有向量保留。迁移完成后记录 `_meta.similar_terms_version`，未完成时 `/similar` 返回 503 并提示命令；失败可重跑。新增或更新文档自动建立新字段。五语停用词来自 `backend/stopwords/similar_*.txt`，建索引时嵌入 ES 设置；修改文件不会热更新现有分析器。v10 过滤国家、城市、土地、地点称谓，以及英语 by/beside/near、法语 au/aux、西语 al/junto 等位置连接词，保留「河／川／river／río」等实义词。

所有地点类型参与检索，排除所选地点，不以 meaning_id 加分；响应中的 `threshold` 保留为 null 以兼容客户端。侧栏展示全部结果，地图用浅蓝色虚线地表弧线连接它们；河流、湖泊等使用代表点。`/related` 仍按 meaning_id 提供严格同义接口，首页分类与普通搜索保持原有逻辑。多语言投票不能保证词源正确，宽泛关联仍需用真实地点评估。

数据和 CLI/API 说明见 [backend/README.md](../backend/README.md)。旧 TypeScript 搜索路由、示例搜索和 embedding 适配代码已删除。data/seed.json 仅保留为历史来源资料，不参与运行时读取。

features-v10 的每条 nested `literal_meanings` 释义中保存 `embeddings_qwen3_7_text_embedding_512_v1`，其 `zh`、`en`、`ja`、`fr`、`es` 分别是 512 维、cosine 的 `dense_vector` 字段。向量按已有译文离线批量预处理，缺失译文的语言保持空白；补齐脚本和记录见 [向量说明](embedding-pilot.md)。前端默认「文本」继续使用 `/similar`；切到试验性的「向量」后调用 `/api/features/{feature_id}/vector-similar?lang=zh&min_similarity=0.60`。源地点直接使用 ES 中已保存的当前语言 document 向量，ES 用 nested `script_score` 与候选的同语言 document 向量计算精确余弦，`min_score=1+min_similarity`，PIT 与 `search_after` 取回全部过门槛地点。多条释义逐对比较，再按地点保留最高分与源／命中释义序号；同一语言、阈值及数据版本下，反向查询的分数与关联关系一致。在线查询不调用模型、不依赖查询向量缓存或百炼密钥；仅离线新增或更新向量时需要模型。接口不返回 512 维数组；源地点缺少当前语言向量时返回 `available=false`，不会回退文本搜索。前端滑杆可在 0.50–0.90 调整门槛并显示每个结果的原始余弦分数。默认 0.60 暂时沿用，文档向量互相比的分数分布需重新校准，高分仍需人工核实。覆盖扩大后仍需重新评估精确搜索延迟，再考虑近似 kNN。已有托管版本不随本地改动更新；部署新版需要可访问的 Python 后端。

底图 place 标签点击通过提供方专属 ID 解码得到 node/way/relation 标识，调用 /api/features/resolve，精确查询 external_ids.osm。无匹配和身份冲突分别展示状态，服务异常可重试；不使用模糊名称匹配。现有示例的映射也存入 ES，锚点 JSON 不再决定运行时关联。
