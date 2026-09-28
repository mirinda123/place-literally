# 20 个地点的字面含义向量试跑

`backend.embed_meanings` 按 `--plan` 清单选择已有五语释义的地点；默认清单 `data/embedding-pilot-20.json` 有 10 个国家和 10 个城市，新增清单 `data/embedding-pilot-30.json` 有另外 15 个国家和 15 个城市。每条 `literal_meanings` 释义的 `zh/en/ja/fr/es` 译文分别调用百炼 `qwen3.7-text-embedding`，以 `text_type=document` 生成 512 维向量，写入 ES `features-v9` 的 `embeddings_qwen3_7_text_embedding_512_v1` 对应语言字段。它只向量化**现有释义文本**，不重新推断或翻译地名。

百炼的 `instruct` 仅在 `text_type=query` 生效。脚本的 `--instruct` 默认值是：

> Given the literal meaning of a place name, find countries and cities whose names have a similar literal meaning.

写入索引的 document 向量不带 instruct。试跑结束时，脚本额外为中国第一条中文释义生成一个带 instruct 的 query 向量，计算它与本次 20 个地点的中文 document 向量的余弦相似度，报告前五名。默认 `/similar` 仍使用文本搜索；前端切到「向量」才调用 `/vector-similar`，用同一个 instruct 生成当前语言的 query 向量。

在项目根目录运行：

```powershell
# 只核对计划、向量数量，不调用模型或写 ES
backend\.venv\Scripts\python.exe -m backend.embed_meanings

# 在环境变量或未纳入 Git 的 backend/.env 中设置 DASHSCOPE_API_KEY 后运行
backend\.venv\Scripts\python.exe -m backend.embed_meanings --apply

# 续批：另外 15 个国家、15 个城市；单独保存缓存和报告
backend\.venv\Scripts\python.exe -m backend.embed_meanings --plan data\embedding-pilot-30.json --output-dir work\embedding-pilot-30 --probe-feature-id osm-node-249399280 --apply
```

可用 `--instruct "..."` 修改英文查询任务说明，`--probe-feature-id` / `--probe-language` 修改诊断起点；`--batch-size` 的范围为 1–20。`--force` 会依据**当前释义文本**重新填充已有向量，同一文本的缓存仍会复用。脚本从环境变量 `DASHSCOPE_EMBEDDING_URL` 读取可选的百炼 HTTPS 接口地址，默认使用官方 DashScope 原生接口。密钥只从 `DASHSCOPE_API_KEY` 读取，不能写进选点文件、代码或报告。

成功的模型结果按模型、维度、文本类型、instruction 和输入文本散列后缓存在被 Git 忽略的相应 `work/embedding-pilot-*/cache/`，中断续跑可避免重复请求。每个地点写入前会重新读取 ES 并比较译文，以 ES 的序号和主分片任期做并发更新；更改过的译文不会被旧向量覆盖。总结在相应的 `report.json`，不含密钥或完整向量。

每次运行会在终端和相应的 `run.log` 记录 UTC 开始时间、准备阶段、每批实际 API 请求、查询探针、ES 写入和总耗时。`--apply` 的 `report.json` 还包含 `timing`：起止 UTC 时间、各阶段秒数、累计 API 耗时及逐批耗时。缓存命中的向量不会计作 API 请求；dry-run 的时间信息出现在终端与 `run.log`，不会覆盖上一次实际写入的报告。早于此日志功能生成的旧报告没有精确耗时。

脚本读取已有记录时显式设置 `_source.exclude_vectors=false`；ES 默认从返回的 `_source` 中省略 dense vector，否则续跑会误判为缺少向量。完成后的默认 dry-run 应报告 `pending_vectors: 0`。

2026-09-26 试跑结果：20 个地点、32 条释义，共 160 个五语向量；159 段不同文本，9 次 API 调用，3,517 tokens。ES 核对到 20 个根文档及每种语言 32 条嵌套向量。中国的中文 query 在这 20 个地点中靠前的是北京、南京、巴黎、韩国、名古屋；这不是最终连线结果，也说明向量分数仍需用正反样例校准。后端所有公开接口在 `_source` 中排除向量字段，浏览器不会收到数百维数组。

2026-09-27 续批结果：另外 30 个地点、45 条释义，共写入 225 个五语向量；13 次 API 调用（12 个 document 批次和 1 个 query 探针）、4,709 tokens，总耗时 10.635 秒，其中 API 累计 6.934 秒、ES 更新 1.290 秒。报告位于 `work/embedding-pilot-30/report.json`。两批合计 50 个地点、77 条释义、385 个向量；ES 逐条核对五种语言均为 512 维，续跑 dry-run 的待处理数量为 0。

新增向量连线后，用 0.60 门槛对这 50 个地点的五语释义做了 250 次**只读**检索，完整候选、原始余弦分数及释义序号保存在本地 `work/vector-similar-audit-20260927.json`，未保存向量或密钥。中、英、日、法、西分别产生 196、62、309、107、93 条有向连线；56 次查询没有过门槛结果。中国的中文查询命中京都（0.6259）、广州（0.6196）、北京（0.6154）、南京（0.6021），说明 0.60 仍可能包含语义上不可靠的关系。界面因此标明「试验」，显示每条结果分数并允许调整门槛；高分不能代替词义核实。

同日进一步对 `features-v9` 的**全部现有字面释义**运行 `python -m backend.embed_all_meanings --apply --output-dir work/embedding-all-20260927`：522 个地点、731 条释义中原有 385 个向量，本次为 472 个地点补齐 3,258 个向量。3,208 段不同待处理文本分 161 次模型请求，共 70,001 tokens，耗时 97.943 秒；无写入冲突。写入后独立复核为 3,643 个向量、现有译文的待处理数量为 0。首尔、大诺夫哥罗德、别尔哥罗德、东京各有一条旧示例释义缺少日、法、西译文，对应 12 个语言位置没有生成向量；脚本不会为缺失译文杜撰文本。运行报告与缓存位于被 Git 忽略的 `work/embedding-all-20260927/`，可以用同一目录续跑。扩容后在 0.60 门槛下，中国的中／英／日／法／西查询分别命中 15／3／48／18／17 个地点，结果量已明显增加，需要继续按语言评估门槛和误连。
