# 主要城市名称采集与导入

从项目根目录运行，Python 使用现有后端虚拟环境：

```powershell
# 可选：先统计候选节点（不是最终入选数量）
.\backend\.venv\Scripts\python.exe -m scripts.collect_osm_cities --count

# 获取城市名称，默认分三批全球查询；已有缓存时不重复请求
.\backend\.venv\Scripts\python.exe -m scripts.collect_osm_cities

# 检查并导入现有 features-v5
.\backend\.venv\Scripts\python.exe -m backend.import_countries --cities --dry-run
.\backend\.venv\Scripts\python.exe -m backend.import_countries --cities
```

也可限制国家：

```powershell
.\backend\.venv\Scripts\python.exe -m scripts.collect_osm_cities --countries CN JP FR --output-dir work/osm-cities-selected
.\backend\.venv\Scripts\python.exe -m backend.import_countries --cities --input work/osm-cities-selected/cities.json
```

国家模式按两字母代码查找 `ISO3166-1`、`boundary=administrative`、`admin_level=2` 的 Overpass 区域，区域必须唯一存在。未找到或存在多个候选时报告错误，不把它当成“没有城市”。这不是对所有国家和地区都适用的边界映射；需逐一处理例外。全球模式不需要国家边界，也不推断城市所属国家。两种模式都只采集名称节点，跨区域相同节点按 OSM ID 去重。

## 筛选规则

- `capital=yes` 或 `capital=2` 的非国家地点节点：保留。
- `capital=4`：保留；它表示第 4 级行政区首府，不能保证涵盖所有国家的一级行政区首府。
- `place=city` 或 `place=town`，有效人口至少 50,000：保留。
- 人口缺失或无法解析的 `city`：保留并单独统计，不能保证实际人口达到门槛。
- 其他普通小城市、人口未知的城镇、普通村庄和街区：不收录。

`--min-population 100000` 可改为十万人门槛。城镇查询先用数字形式及最短字符数缩小候选范围，再在本地执行准确门槛判断。纯数字及明确的千位逗号、空格人口值可以解析；其他格式不推测。人口只用于筛选，不生成新的统计数据。人口可能缺失、过期或使用不同统计范围。

## 缓存、重试和输出

默认在 `work/osm-cities/` 写入：

- `global-cities-50000.raw.json`、`global-towns-50000.raw.json`、`global-capitals-50000.raw.json` 或逐国家的原始缓存，包含原始标签、查询、端点和采集时间。
- `cities.json`：入选地点的所有可识别语言名称、原名、OSM 身份、坐标和筛选依据。
- `report.json`：候选与入选数、筛选原因、语言覆盖及许可。
- `failed-run.json`：失败范围；失败时不会覆盖已有的有效导入文件。

全球分批和逐国家模式都串行执行，请求完成后至少间隔 10 秒。HTTP 429、502、503、504 或连接错误最多尝试三次，以 30 秒、60 秒退避，尊重更长的 `Retry-After`。要求等待超过五分钟时退出。重试耗尽后停止整个采集，不继续向其他范围发送请求；重新运行相同命令即可复用已完成的缓存。响应包含运行时错误的部分结果不会导入。

`--refresh` 显式更新缓存；不更换 IP 或端点绕过限流。全球模式分为城市、城镇、首府三批。它减少逐国请求的数量，但仍可能遇到服务器繁忙或超时；必要时改用较小的国家范围。全球城镇批次允许五分钟、256 MiB 的查询资源，其他查询允许三分钟、128 MiB；解压后的响应上限为 128 MiB。数量统计与实际下载分别发送请求。首次采集遇到全球综合查询、城镇与人口标签交叉查询和全量城镇查询超时，最终通过人口字符串形式预筛选缩小城镇候选范围，再在本地筛选。

参考 [Overpass 公共实例说明](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html)。其约每天一万请求、1 GB 下载是宽泛参考，不是可用性保证。长期高频或更大规模采集应使用离线提取或自建服务。

## ES 合并规则

复用国家导入器的 `--cities` 模式，默认输入为 `work/osm-cities/cities.json`：

- 按 `external_ids.osm` 合并，新增 ID 为 `osm-node-<ID>`。
- 所有名称语言进入 `names`，原名进入 `names.und`。
- 已有记录保留名称、坐标、类型、feature ID 和字面含义，仅补充缺少的语言名称。
- 新记录的 `literal_name`、`meaning_id` 为 `null`，`literal_meanings` 为空。
- 不删除国家和已有城市；重复导入不会新增重复记录。
- 写入前在 `work/osm-city-imports/<时间>/` 备份现有文档和操作计划，记录逐批写入错误。

人口、首府标签等筛选信息保留在本地采集文件，不扩展 ES 的业务字段。原始多语言数据归属 **© OpenStreetMap contributors**，采用 [ODbL](https://www.openstreetmap.org/copyright)。本流程不生成或翻译字面含义。

## 数据量适配

导入前计算新增语言所需的 ES 映射字段数。每种语言包含文本字段和 `.raw` 子字段；超过当前容量时按 500 个字段向上扩容，最高自动调整到 5,000。`--dry-run` 会报告调整前后容量，正式导入备份原映射。未来覆盖更多语言时应重新评估字段结构，不能无限增加此限制。

检索使用内部 `search_names` 字段，通过 `copy_to` 汇总所有语言名称，避免查询同时展开数百个语言字段而超过 ES 子句限制。它仅存在于倒排索引，不增加业务文档 `_source` 的字段；现有名称和字面含义保持原样。首次导入会更新旧字段的映射并重新索引已有名称。完整名称使用 `.raw` 匹配，分词名称使用短语匹配，避免跨不同语言的名称值拼出一个结果。

地图改用 `/api/map-features` 的 `after` 游标分页，每页最多 1,000 条，避免原来 10,000 条的加载限制。地图列表只返回首期显示语言、未确定语言原名及含义等必要字段；完整名称仍可通过地点详情、OSM 关联和搜索接口获取。侧栏每次显示 100 条，可继续展开，避免一次渲染数万行。地图目前仍会加载全部坐标，更大规模需要按视野加载。

## 首次运行结果

2026-09-21（香港时间）完成三批查询，共 35,679 个候选节点，入选 13,544 个，覆盖 712 个语言标签。ES 新增 13,534 条并补充原有 10 个城市的名称，与 225 个国家节点合计 13,769 条；没有新增字面含义。当前包含 9,619 个 city/metropolis、3,881 个 town，以及 44 个通过首府规则保留的其他类型节点。

本次遇到查询超时，没有收到 HTTP 429。现有数据已备份；验证结果保存在 `work/osm-cities/verification.json`。原有 235 条记录的名称值、坐标和字面含义均保留，所有 OSM 标识唯一；七种目标语言的巴黎搜索、OSM 关联以及 14 页地图加载均验证通过。
