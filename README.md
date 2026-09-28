# Place, Literally

**Explore what place names mean—and where meanings meet.**

一个按字面含义探索地名的开源地图原型。点击有释义的地点，按当前界面语言查找所有类型中含义相近的地点，并用地图弧线连接。

## 本地运行

需要 Node.js >= 22.13、Python 3.11+ 和 Elasticsearch 9.x。先按 [后端 README](backend/README.md) 导入数据并启动 Python 服务，再启动前端：

```sh
npm ci
npm run dev
```

前端默认 http://localhost:5173/，Python 接口文档 http://127.0.0.1:8000/docs 。Vite 将 `/atlas-api/*` 转发到 Python 的 `/api/*`，目标由 `ATLAS_BACKEND_URL` 配置。

## 数据与搜索

应用使用 ES 的 `features-v10` 索引：每个地点保存 feature_id、kind、names、location、literal_name、按释义排列的 literal_meanings、meaning_id，另有可选 external_ids.osm。字面含义的中文、英文、日文分别使用 IK、不删除停用词的 English、Kuromoji 分词。前端通过 Python API 读取地点、查询名称及含义，无数据或请求失败时显示空状态或重试提示，不回退本地示例。

搜索由 Python 和 Elasticsearch 完成。中文地名使用 CJK，中文字面含义使用 IK，英文含义使用 English（保留停用词），日文含义使用 Kuromoji；完整名称支持规范化匹配，概念与主题采用项目分组配置。地点连线默认使用文本相近搜索，也可以切换到试验性的向量模式并调节余弦相似度门槛；当前 718 个有字面释义的地点，其全部现有译文都已写入向量。旧前端 `/api/search` 路由、TypeScript 示例搜索和旧向量生成脚本及其专用测试已移除。

- [地点导入数据](data/features.json)：当前 11 个已关联 OSM 的示例地点；前端不直接读取这个文件。
- [含义分组配置](data/meaning-groups.json)：首页分类和普通搜索使用的概念与主题配置；点选地点的相近查询直接检索 ES 释义。
- [内容来源与许可](data/feature-attributions.json)：早期示例地点的来源与许可记录，供内容核对；详情卡暂不展示。
- [OSM 国家名称采集与导入](docs/osm-country-collection.md)：批量获取国家节点的多语言名称，并按 OSM 身份增量写入 ES；当前本地包含 225 个国家名称节点。
- [主要城市名称采集与导入](docs/osm-city-import.md)：按地点类型、人口和首府标记筛选，支持缓存、串行请求及失败后继续。
- [搜索架构](docs/search-architecture.md)
- [前期产品设计](docs/product-design.md)：历史方案，实施现状以本 README 和后端文档为准。

`data/seed.json` 与 `data/translation-draft.jsonl` 仅保留为原始来源和历史翻译草稿，不参与运行时搜索或地图读取。字面含义和分组仍是待审核内容；搜索“水”无结果仅表示未收录。

## 地图交互

右上角语言菜单支持简体中文、英语、西班牙语、法语和日语，使用现有 Radix/shadcn Select。韩语文案和数据保留，但暂不提供选择入口。
选择保存在本机浏览器，切换时保留当前地点和地图视角。搜索、侧栏、详情和操作文案一起切换；
详情卡优先显示当前语言的 `names` 与 `literal_meanings`，原名单独列出，不再堆叠全部译文。
缺少当前语言时回退到已收录语言并标明；没有释义时显示空状态。底图自身地名仍沿用提供方的原生多语言标签。

React + TypeScript、MapLibre GL JS、Turf、shadcn/ui 和 Radix。OpenFreeMap 提供 OSM 在线街道底图，支持球形地球和街区缩放；Natural Earth 作为简化备用底图。

点击底图 place 图层的国家、城市、城镇等地名，按当前提供方的 ID 编码还原 OSM 身份，调用 Python `/api/features/resolve` 精确查询 external_ids.osm。未收录、映射冲突、无可用标识和服务异常分别显示提示。换底图提供方时需要重新确认 ID 编码。

当前本地 ES 的 13,769 个地点全部已关联 OSM 节点，包含 225 个国家名称节点和 13,544 个主要城市、城镇及首府节点。新增地点只收录名称，暂未填写字面含义。未关联的迦太基古城已从当前数据集中移除。在线地图直接装饰原生 place 图层：按 ES 的 OSM 映射设置标记和文字颜色，保留底图坐标、缩放门槛、地点等级筛选和文字避让，不再叠加所有地点的独立点图层。锚点历史记录保存在 `data/map-anchors.json`；运行时关联不依赖该文件。

覆盖式侧栏不改变地图尺寸。底图标签因避让隐藏时，标记一起隐藏；标记是否随缩放出现或消失沿用底图规则，国家等原本无图标的标签不额外添加圆点。关联线在街区尺度下淡出；键盘用户可使用侧栏和可聚焦地点列表。简化备用底图最多显示当前结果中的 100 个标注。地图通过游标分页加载必要字段，侧栏分批显示；更大规模仍需要进一步实现按视野加载。

## 验证与部署

`npm test` 检查前端 API、地图身份与标注逻辑；`npm run build` 构建应用。后端集成测试和配置见 [后端 README](backend/README.md)。

前端基于 Vinext/Vite。生产环境需要可访问的 Python API：设置 `VITE_ATLAS_API_BASE_URL` 为包含 `/api` 的 HTTPS 地址并配置后端 CORS，Vite 开发代理不包含在生产构建中。本地修改不会自动更新已有托管版本。

应用新增代码采用 MIT；字面含义衍生内容保留 CC BY-SA 4.0 来源，导入的 OSM 地名锚点保留 ODbL 归属，Natural Earth 备用底图为公有领域。详见 [第三方声明](THIRD_PARTY.md)。
