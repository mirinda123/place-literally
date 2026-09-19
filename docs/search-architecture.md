# 搜索选型：PostgreSQL + pgvector 优先

2026-09-19。结论针对 Literal Name Map 当前的数据结构和阶段，不是通用性能排名。

## 当前实现

- 地图：MapLibre GL JS；地理连线：Turf great-circle；底图：OpenFreeMap / OpenStreetMap 的在线矢量瓦片；缩小显示地球，放大到道路与建筑。Natural Earth 仅作断网时的简化备用底图。
- UI：项目现有的 shadcn/ui（Radix primitives）Button、Input、ToggleGroup、Dialog，Lucide 图标。没有自制地图引擎、弹窗焦点管理或分段选择键盘逻辑。
- `/api/search`：Fuse.js 名称/别名/转写模糊匹配 + 中英语义概念与人工关系图谱。支持“新的定居点”“跟首都有关系的名字”“中心”等表达；不是已接通的大模型，也不理解任意句子。
- 后端存储为随应用发布的版本化 JSON；没有安装数据库。12 个地点的种子包含来源和审核标记。
- 可选向量通道：标准 embedding HTTP 接口 → 内存余弦检索 → RRF 排名融合。未提供模型凭据和生成向量时，明确使用概念检索，不伪造向量或置信度。

## 为什么选 pgvector，而不是现在上 ES

| 方案 | 合适的地方 | 这里的取舍 |
| --- | --- | --- |
| 小规模内存索引 | 少量版本化记录，直接检索，容易部署 | 本次原型采用；需实测加载、内存与并发后决定升级 |
| PostgreSQL + pgvector | 地点、名称、词源候选、来源、审核和关系同库存储；精确或近似向量检索 | 正式后端首选，避免先维护主数据库和额外搜索集群 |
| Elasticsearch | 原生全文检索、语言分析与向量混合，支持 RRF | 当复杂分词、拼写、全文高亮和相关性调优成为核心需求时再评估 |
| Qdrant | dense/sparse 混合、payload 筛选、多阶段向量检索 | 向量检索需要独立扩容时再评估；关系数据仍需有明确主存储 |

ES 本身支持向量检索，不能简单理解为“向量数据库负责语义，ES 只负责关键词”。对于本项目，更重要的是选择能方便维护词源来源、多个名称和审核关系的系统。[Elasticsearch 混合搜索](https://www.elastic.co/docs/solutions/search/hybrid-search)、[pgvector](https://github.com/pgvector/pgvector)、[Qdrant 混合查询](https://qdrant.tech/documentation/search/hybrid-queries/)

PostgreSQL 自带的全文配置不等于中文分词；把 `english` 换成 `simple` 也不会自动解决中文词边界。第一阶段用明确的别名/概念词典和多语言 embedding，后续再引入经过评估的中文分词。ES 有 Smart Chinese 插件，但增加一个 ES 服务也意味着索引同步和运维。[PostgreSQL parser](https://www.postgresql.org/docs/current/textsearch-parsers.html)、[Elastic Smart Chinese](https://www.elastic.co/docs/reference/elasticsearch/plugins/analysis-smartcn)

## 检索策略

1. 明确地名命中优先，保护短地名和专名。
2. 使用直译、词素、规范含义和修饰概念检索。不要把地理位置或旅游介绍混入语义文本。
3. 在相近/主题范围内，向量可以补充候选。原始含义保留，“北/南”“新/旧”“白/黑”不能被泛化成同义。
4. 融合候选使用 RRF，不把 Fuse 分数或将来 BM25 分数直接加到 cosine 上。
5. 搜索候选的相关性不等于词源可信度；地图的同义关系仍由审核后的分析记录决定。

当前概念检索对否定条件会明确提示不支持；不会把“不要首都”按“首都”返回。尚未收录水相关词义时，搜索水不会返回沿海地点。

## 接通 embedding 通道

在未提交的 `.env.local` 中设置 `EMBEDDING_URL`、`EMBEDDING_MODEL` 和需要时的 `EMBEDDING_API_KEY`，然后：

```sh
npm run embeddings:generate
npm run dev
```

接口采用 POST `{model,input:[text],encoding_format:"float"}`；返回 `{data:[{index,embedding}]}`。需使用文档和查询可直接共用的模型处理格式。需要特定 query/passage 前缀的模型（如 E5）不能直接套用当前通用适配器，应先把该模型的预处理规则同时加入生成脚本和查询实现，并增加模型版本校验。

生成脚本按整个批次校验维度、数量和顺序后才替换索引。应用验证索引的数据版本和模型名；模型调用失败会回退概念检索，并在页面显示提示。`SEMANTIC_MIN_SCORE` 只是待评估的召回门槛，不是置信度。默认未接通外部模型，因此没有发生模型 API 计费调用。

托管版本需通过托管平台配置服务端环境变量；本地 `.env.local` 不会发布。公开提供收费模型接口前应在部署平台加限流/额度控制。当前 Sites 部署保持所有者私有。

## 后续迁移契约

保留前端消费的 `analysis_id`、`place_id`、`reason`、`matched_concepts`、`kind` 字段。把向量检索实现从内存替换为 pgvector，不改变地图。

建议关系表包括 `places`、`names`、`analyses`、`sources`、`analysis_sources`、`meaning_groups`、`cluster_memberships`；向量记录绑定 `analysis_id + model_version + data_version`。确定模型维度后再创建对应的 vector 列和索引。不要为了演示先锁死未知模型的维度。

等数据、国家/类型过滤和真实查询稳定后，用同一套中英文评估问题比较召回、错误关联、过滤后的结果、启动时间和并发延迟，再决定 HNSW 或其他搜索引擎。不采用未经测试的“超过 N 条必须换 ES”规则。
