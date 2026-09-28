# 中国省级地名批次

本批按用户指定的 34 个地名处理：23 个省级名称（含台湾）、5 个自治区、4 个直辖市、香港和澳门。目标是地图地名标签的字面含义，不推断行政边界或政治归属。

31 个标签来自 Overpass 快照中的 `place=state` 节点，覆盖 22 个省、5 个自治区、天津／上海／重庆和澳门。北京、香港、台湾在当前地图数据中没有对应的 `place=state` 标签，因此复用 ES 里已有的 `place` 标签节点，分别为 `node/25248662`、`node/24330691`、`node/432425099`。这三条记录的 `kind` 保持既有值；`kind` 是地图标签类型，不是行政地位声明。标签节点的 OSM ID 用于地图点击关联。OSM 中国标签说明见 [China/Boundaries](https://wiki.openstreetmap.org/wiki/China/Boundaries)；[OpenMapTiles place 层](https://openmaptiles.org/docs/schema/#place)公开了地名标签的 `osm_id` 和 `class`。

在项目根目录运行：

```powershell
backend\.venv\Scripts\python.exe -m scripts.collect_osm_china_regions
backend\.venv\Scripts\python.exe -m backend.import_countries --regions --dry-run
backend\.venv\Scripts\python.exe -m backend.import_countries --regions
backend\.venv\Scripts\python.exe -m backend.plan_china_regions
backend\.venv\Scripts\python.exe -m backend.prepare_china_regions
backend\.venv\Scripts\python.exe -m backend.translate_meanings --kind selected --feature-id-file work\osm-china-regions\feature-ids.json --guidance-file backend\prompts\china_regions.txt --languages zh,en,ja,fr,es --model gpt-6-sol --reasoning-effort high --review-existing --apply --timeout 600
```

采集脚本缓存原始 Overpass 返回，按预期中文短名逐一匹配，缺失或重复会中止。`regions.json` 只收录 OSM 已有的名称与坐标，不生成字面含义。ES 导入前会保存原文档备份，且不会改写已有释义。`feature-ids.json` 由导入后对 34 个 OSM ID 做唯一性核对生成；它包含 31 个新 `state` 文档和三个已有文档。省级标签的中文原名优先固定为 OSM 的 `name:zh-Hans`，没有时使用 `name:zh`，避免模型因别的语言标签更短而选错原名；已写入的释义不会被这一步清除，除非明确指定 `--reset-feature-id`。翻译脚本对成功结果逐条备份并写入 ES，`uncertain` 结果保留空白，模型草稿仍需人工审校。
