# mcp-server API

對 wiki 的唯讀查詢 API。Base URL：`http://localhost:8002`。
所有讀取都 **PG 優先**（關鍵字走 `pg_trgm`，語意走 pgvector cosine），PG 不可用時
退回掃 MinIO `wiki.json`。

> 名詞：**PG-first** = 先查 Postgres（快），失敗退回 MinIO；**hybrid** = 關鍵字 +
> 語意兩種搜尋用 RRF（倒數排名融合）合併；**cosine** = 向量夾角相似度。

## `GET /list_apis?module=<optional>`
`{"modules": {"<module>": ["GET /x/items", ...]}}` —— 所有 module / endpoint。

## `GET /search_apis?query=<q>`
PG 索引 + embedding 都在時為 **hybrid**（向量 + 關鍵字 RRF），所以改寫過的問法也命中
（「undo deleted rows」→ `/recover` endpoint）；否則退回 `pg_keyword` 再 `wiki_scan`。
向量側有 `API_SEARCH_MIN_COSINE`（預設 0.5）下限，不相關問句回空。
`{"results":[{module,api_key,description,source_app,score?}], "count":N, "mode":"hybrid"|"pg_keyword"|"wiki_scan"}`。

## `GET /semantic_search?query=<q>&top_k=10`
向量相似度（cosine）。把 query 轉成向量，依 `1 - (embedding <=> query)` 排序 `api_entries`。
`{"results":[{module,api_key,description,source_app,score}], "mode":"semantic"|"keyword_fallback"}`。

## `GET /get_api_detail?module=<m>&api_key=<METHOD /path>`
`{"detail":{method,path,description,source_app,source_version, ...}}`，找不到回 not-found。

## `GET /wiki_info`
`{"modules":N,"total_endpoints":M,"vector_index":{available,semantic_search,entries,embedded,...}}`。

## `GET /list_concepts`
跨應用概念（由 wiki-processor 的 `/admin/rebuild-concepts` 建立）。
`{"concepts":{"<name>":{description,apps:[...],related_count}}}` —— 未建立前為空。

## `GET /get_concept?name=<name>`
`{"concept":{description,related:["<module>::<api_key>", ...],apps:[...]}}` 或 404。

## `GET /get_overview?app=<app>`
匯入時合成的每-app 總覽。`{"overview":{text,updated_at}}` 或 404。

## `GET /skill?name=<skill-name>`
把 wiki 打包成 Anthropic Skill 資料夾。
`{"files":{"<name>/SKILL.md":"...","<name>/references/concepts.md":"..."}}`。

## `GET /graph`
知識圖譜。`{"nodes":[{id,type,module?}],"edges":[{source,target,weight,kind}]}`。
邊：`shared_source`（4.0，共用同一來源檔的 endpoint）、`concept`（3.0，概念→endpoint）。

## `POST /cache/invalidate`
`{"source_app":"my-app"}` → 清掉該 app 的快取（wiki-processor 寫入後呼叫）。

## `GET /health`
`{"status":"ok"}`

## 知識文件（prose / 參考文件，非 API spec）
由 `wiki.knowledge`（wiki-processor 從 `knowledge` 類文件建立）提供。

- `GET /list_knowledge` → `{knowledge: {doc_id: {title, source_app, topics}}}`
- `GET /get_knowledge?doc_id=` → `{knowledge: {title, summary, topics, key_points, ...}}` 或 404
- `GET /search_knowledge?query=` → `{results: [{doc_id, title, summary, source_app, score?}], count, mode}`
  —— PG 索引 + embedding 在時為 **hybrid**（向量 + 關鍵字 RRF），否則 `keyword_fallback`
  （掃快取 wiki 的子字串）。cosine 下限（`MCP_KNOWLEDGE_MIN_COSINE`，預設 0.5）擋掉不相關的
  近鄰。見 [architecture/hybrid-knowledge-search.md](architecture/hybrid-knowledge-search.md)。

## 原生 MCP —— `POST /mcp/`
真正的 [Model Context Protocol](https://modelcontextprotocol.io) server（Streamable
HTTP transport），掛在同一個 app 上，讓 Claude / agent 原生連線，不用自寫 REST client。
無狀態（`stateless_http=True`）：可水平擴展、無 session 黏滯。工具是與 REST 同一套
`QueryService` 的薄包裝：`search_apis`、`semantic_search`、`list_apis`、`get_api_detail`、
`list_concepts`、`get_concept`、`get_overview`、`wiki_info`、`search_knowledge`、
`get_knowledge`、`list_knowledge`。知識文件另以 MCP **resource**（`knowledge://{doc_id}`）
形式提供 —— 慣用的唯讀 context。

連線（Claude Code）：`claude mcp add --transport http llm-wiki http://localhost:8002/mcp/`

正式環境：設 `MCP_ALLOWED_HOSTS`（逗號分隔）開啟 DNS-rebinding 保護；不設 = 關閉（dev 預設）。
設計緣由見 [architecture/mcp-transport.md](architecture/mcp-transport.md)。

語意搜尋怎麼運作（query → embed → pgvector cosine → 排序）的完整實例，見平台文件
`docs/examples/real-semantic-walkthrough.md` 與 `docs/architecture/vector-search.md`。
</content>
