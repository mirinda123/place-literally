# Literal Name Map

**The world has fewer names than you think.**

一个按字面含义探索地名的开源地图原型。点击 Naples，可以看见同样意为“新城”的 Carthage 和 Novgorod；切换“相近”与“主题”，探索更宽的联系。

## 本地运行

需要 Node.js >= 22.13。项目当前位于 `D:\Projects\literal-name-map`。

```sh
npm ci
npm run dev
```

打开终端输出的地址，默认 http://localhost:5173。`npm test` 检查搜索和归一规则；`npm run build` 构建应用。

## 已实现

- MapLibre GL JS 世界地图、原生图钉与地名标注、Turf 大圆连线、覆盖式侧栏。
- shadcn/ui + Radix 的按钮、输入、范围选择，Lucide 图标。
- 特定名称的词源卡、拆词、来源链接和待复核标记。
- 同义 / 相近 / 共同主题三个层次；宽主题不画同义连线。
- 中英概念检索与 Fuse.js 名称模糊搜索；搜索结果解释命中原因。
- 服务端 `/api/search`，可选 embedding 通道与 RRF 融合，未配置时使用概念搜索。

## 数据与搜索边界

种子包含 12 个地点、13 个名称、12 个词源分析。11 个现代地点使用当前 OpenFreeMap 底图的地名锚点，记录在 `data/map-anchors.json`；迦太基古城仍为近似演示点。翻译与分组是带来源的草稿，并非已审核的全球词源数据库。不同名称、不同历史阶段、不同词源假说应分开记录。搜索相似度不代表词源可信度。

当前没有配置模型或向量数据库：概念匹配覆盖有限表达，无法理解任意自然语言。搜索“水”没有结果表示未收录，不能推断全球不存在水相关地名。

- [种子数据](data/seed.json)
- [批量翻译草稿](data/translation-draft.jsonl)
- [数据模型与交互设计](docs/product-design.md)（前期设计，实施现状以本 README 为准）
- [后端与语义搜索选型](docs/search-architecture.md)

正式后端推荐 PostgreSQL + pgvector，将地名、来源、审核关系和向量放在同一存储中；ES 的复杂全文能力成为明确需求时再引入。当前小样本使用版本化 JSON 与内存检索。

## 可选模型接入

把 `.env.example` 复制为 `.env.local`，填写受支持的 HTTPS embedding 端点、模型和密钥。运行 `npm run embeddings:generate` 生成索引，再启动或构建。查询必须使用相同模型、维度和预处理。详细限制、校准要求和迁移路径见搜索选型文档。默认不会发送请求到任何模型服务。

## 技术与部署

React + TypeScript，基于 Vinext/Vite 的应用与服务端路由；使用 OpenFreeMap / OpenStreetMap 在线街道底图，无需地图服务 API key；需要联网，细节取决于 OSM 覆盖。Natural Earth 随项目打包作为简化备用底图。当前托管配置在 `.openai/hosting.json`，环境密钥不入库。若自行部署到其他平台，需适配 Vinext 的 Worker 运行环境或迁移路由。

## 贡献

增加地点时保留名称语言、历史时期、词源来源、修改说明和审核状态；一个词源分析可属于多个语义主题。批量翻译只能生成待审核草稿，不能自动升级为“确定”。先扩充真实样本与查询评测集，再调整召回模型和索引架构。

应用新增代码采用 MIT；词源衍生内容采用 CC BY-SA 4.0 并保留逐条来源；导入的地名锚点采用 ODbL；Natural Earth 备用底图为公有领域。详见 [第三方声明](THIRD_PARTY.md)。

## 地图标注

图钉与中英地名使用同一个 MapLibre symbol 图层，随地图一起投影，标注拥挤时文字自动避让，图钉仍可点击。已核实地点按 OpenMapTiles 的 `place` 图层 feature ID 替换底图原标签，不按名称全局隐藏。底图锚点取自 2026-09-13 的瓦片快照（z14），并非建筑入口或行政区域边界；底图更新后应按记录的来源复核，不应仅凭相同名称自动匹配。古城不绑定现代同名城市。键盘用户可使用侧栏或地图上的可聚焦地点列表选择地点。

地名文字按缩放层级显示：全球视角突出当前命中与国家，普通城市在 z2–3 渐显；国家文字在 z6–7 淡出，城市文字在 z12–14 淡出。文字完全隐藏后不再占据标注避让空间，图钉仍保留并可点击查看详情。阈值是本项目的显示策略，不是直接复制底图全部样式规则。
