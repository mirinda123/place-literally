# OSM 国家多语言名称采集

在项目根目录运行（Python 3.11+，脚本仅使用标准库）：

```powershell
.\backend\.venv\Scripts\python.exe scripts/collect_osm_countries.py
```

也可以使用系统的 `python`。默认向 Overpass 发出一次全球范围的 `node["place"="country"]` 查询，下载名称节点及其标签，不下载国家边界。已有本地原始结果时直接复用，不发送网络请求。需要更新时显式运行：

```powershell
.\backend\.venv\Scripts\python.exe scripts/collect_osm_countries.py --refresh
```

可用 `--output-dir <目录>` 更改输出目录；`--attempts 1` 禁用重试。

## 输出

默认输出到已被 Git 忽略的 `work/osm-countries/`：

| 文件 | 内容 |
| --- | --- |
| `overpass-countries.raw.json` | 原始 Overpass 响应、查询语句、端点和采集时间，包含全部原始标签 |
| `countries.json` | 整理后的国家名称节点，供后续审核及导入 |
| `report.json` | 语言覆盖、缺失项、重复国家代码、数据时间与许可 |

每条整理后的记录包含：

| 字段 | 含义 |
| --- | --- |
| `osm` | 完整 OSM 身份，例如 `node/424313582`，后续可放入 `external_ids.osm` 数组 |
| `local_name` | OSM 的原始 `name`，不推断其语言 |
| `names` | 所有符合语言代码形式的 `name:*` 值，键为原始语言标签 |
| `location` | 名称节点的经纬度，不代表国家边界或几何中心 |
| `country_code` | OSM 中已有的两字母国家代码，缺失时为 `null` |
| `wikidata` | OSM 中已有的 Wikidata 标识，仅保留备查，不请求 Wikidata |
| `name_tags` | 所有原始 `name:*` 标签，包括未归类为语言的字段 |
| `missing_languages` | 缺少的目标语言标签：`en`、`zh-Hans`、`zh-Hant`、`es`、`fr`、`ja`、`ko` |

语言键仅做形式筛选，并未通过语言注册表校验；统计中的“语言标签数”不等于经过审核的独立语言数量。`name:etymology`、`name:en:pronunciation` 等不会作为翻译进入 `names`，原始标签仍然保留。`name:zh` 不会被自动当成简体或繁体，缺失统计按精确语言标签计算。名称值不拆分、不改写、不做机器翻译，也不生成字面含义。

## 范围与后续关联

这是 OSM 当前快照里所有 `place=country` **节点**的导出，不是权威主权国家名录。[OSM 的定义](https://wiki.openstreetmap.org/wiki/Tag:place%3Dcountry)还可能包含其他高层级政治实体；未标注的地点、仅存在于边界关系上的名称不在本次查询范围内。不能把记录数量理解为世界国家总数。

记录按 OSM 身份保留，国家代码重复只报告、不合并。导入 ES 时将 `osm` 映射到 `external_ids.osm`；底图能提供同一个 OSM 节点身份时即可精确关联。采集脚本本身不修改 ES。

## 导入 Elasticsearch

先按后端 README 初始化 `features-v5`，再从项目根目录运行：

```powershell
.\backend\.venv\Scripts\python.exe -m backend.import_countries --dry-run
.\backend\.venv\Scripts\python.exe -m backend.import_countries
```

导入器使用 `backend/.env` 的 ES 配置。所有采集到的语言名称进入现有 `names` 对象，原始 `name` 保存为 `names.und`（未确定语言），不增加新的索引或字段结构。国家代码和 Wikidata 等采集元信息留在本地原始文件。

按 `external_ids.osm` 精确查重：已有国家保留 `feature_id`、已有名称、坐标和字面含义，仅补充缺少的名称语言；新国家使用 `osm-node-<ID>` 作为 `feature_id`，`kind=country`，字面含义和分组留空。重复运行不会重复创建记录。OSM 身份冲突在写入前报错，已有记录的并发修改也会触发冲突而不是被覆盖。

每次正式导入在 `work/osm-country-imports/<时间>/` 保存 `before.json` 文档备份、`actions.json` 写入计划和 `report.json` 结果。批量写入不是事务，部分失败时以报告为准，可修复后重新运行。导入不会删除其他地点。

国家采集阶段导入 225 个国家名称节点，与当时原有 10 个城市类地点共计 235 条记录；中国沿用原有记录和字面含义。后续又完成 [主要城市导入](osm-city-import.md)，当前本地总数为 13,769。`data/features.json` 仍是 11 条初始示例，重建索引后需再次运行国家和城市导入器；重新导入示例也应随后运行对应导入器补全其多语言名称。

## 请求与数据许可

参考 [Overpass 公共实例使用说明](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)，使用一次有限规模查询和本地缓存。遇到限流或暂时性错误最多请求三次，以 30 秒、60 秒退避，并遵守较长的 `Retry-After`；服务要求等待超过五分钟时退出，留待以后运行。超时的部分响应不会作为成功结果发布，刷新失败保留已有有效文件。

数据归属 **© OpenStreetMap contributors**，采用 [ODbL](https://www.openstreetmap.org/copyright)。许可和归属同时写入 `report.json`。

验证采集、缓存和错误处理逻辑：

```powershell
.\backend\.venv\Scripts\python.exe -m pytest backend/tests/test_collect_countries.py -q
```
