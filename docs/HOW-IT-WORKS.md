# mcp-server 實際怎麼運作（含真實紀錄）

> 這是**唯讀查詢端**。它對 wiki-processor 建好的 wiki 提供查詢：給人用 REST、給 Claude 用 MCP。
> 下面用**真本地 bge-small embedding + 真 Postgres** 現場跑的真實輸出，拆開兩個關鍵「黑盒子」：
> **hybrid search（混合搜尋）怎麼融合** 和 **MCP 怎麼讓 Claude 連進來**。擷取 2026-06-25。
>
> 想先看整套端到端：見平台 repo 的 `docs/HOW-IT-WORKS.md`。這份只聚焦 mcp-server 內部。

> **名詞**：**hybrid search** 關鍵字 + 語意兩種搜尋一起跑再合併；**RRF（Reciprocal Rank
> Fusion，倒數排名融合）** 只看名次、不管分數尺度地合併兩份結果；**cosine** 向量夾角相似度
> （1 最像）；**PG-first** 先查 Postgres、失敗退回掃 MinIO；**MCP** 讓 AI agent 原生連工具的協議。

---

## 核心：hybrid search 怎麼融合（真實拆解）

問句：**「give a customer their money back」**（跟存的字 `refund`/`charge` 零重疊）。
mcp 同時跑兩臂，再用 RRF 融合。

**關鍵字臂（trigram ILIKE）—— 字面比對：**
```sql
SELECT module,api_key FROM api_entries WHERE embed_text ILIKE '%give a customer their money back%';
```
→ **0 列**（字面沒重疊，純關鍵字會漏掉）。
對照：問 `refund` 就中：
```
 module  |        api_key
----------+-----------------------
 Payments | POST /payments/refund     ← 字面有「refund」才中
```

**語意臂（pgvector cosine）—— 比意思：**
```
mode: semantic
  POST /payments/refund   cos= 0.8032   ← 第 1
  POST /payments/charge   cos= 0.5896
  POST /recover           cos= 0.5792
```
意思上「退錢給客戶」最接近「refund money back to a customer」（0.8032）。

**融合（RRF）→ 最終結果：**
```
search_apis("give a customer their money back")  →  mode: hybrid  →  POST /payments/refund（第1名）
```
**這代表什麼：** 關鍵字臂這題掛蛋，語意臂救回來，RRF 把兩臂名次合併 → 正確答案排第 1。
**為何要兩臂**（2026 benchmark）：純向量 ≈ 純關鍵字，單獨都不夠；**融合**才贏（hybrid 79% vs
58%）。所以兩臂一起跑、RRF 合併，不是只挑一種。
**防雜訊**：語意臂有 cosine 下限（`API_SEARCH_MIN_COSINE` 預設 0.5）擋掉不相關近鄰。

---

## 降級（graceful degradation）—— 永遠答得出來

`mode` 欄告訴你走了哪條路：

| 情況 | mode |
|------|------|
| PG + embedding 都在 | `hybrid`（API）/ `semantic`（純向量）/ `hybrid`（知識） |
| 有 PG、沒 embedding | `pg_keyword` |
| PG 掛了 | `wiki_scan` / `keyword_fallback`（退回掃 MinIO 快取） |

**這代表什麼：** Postgres 或 embedding 服務掛掉，查詢不會整個壞 —— 自動退到較弱但能用的路。
`pg_reader` 還有**斷路器（circuit breaker）**：PG 連續失敗就暫時跳過、直接走 fallback，
不一直撞死節點。

---

## 查詢加速：query embedding 有 LRU 快取

每次語意/hybrid 查詢都要把**問句**轉成向量（呼叫 embedding 服務）。重複問句不必再算 ——
`QueryEmbedder` 對問句做 **LRU cache（最近最少用快取）**。
**實證**：併發重複查詢吞吐 **57 → 221 q/s**。大小由 `QUERY_EMBED_CACHE` 調。

---

## MCP：Claude 怎麼連進來

人：`claude mcp add --transport http llm-wiki http://localhost:8002/mcp/`

底層是標準 MCP 協議（Streamable HTTP、無狀態）。真 handshake：
```bash
curl -s -X POST localhost:8002/mcp/ -H 'Accept: application/json, text/event-stream' \
 -H 'Content-Type: application/json' \
 -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}'
```
→ `serverInfo: {'name':'llm-wiki', ...}  protocol: 2025-03-26`

真的呼叫工具 `search_knowledge("recover lost data")`：
```json
{"results":[{"doc_id":"oracle-kb:oracle_flashback","title":"Oracle Flashback",
 "summary":"Oracle Flashback is a recovery feature ... point-in-time recovery ...",
 "source_app":"oracle-kb","score":0.0167}], "mode":"hybrid"}
```
**這代表什麼：** Claude 把這些查詢當「工具」直接呼叫，邏輯和 REST 完全同一套（MCP 只是薄包裝）。
知識文件另以 MCP **resource**（`knowledge://{doc_id}`）形式提供。
**壞了會怎樣：** 正式環境設 `MCP_ALLOWED_HOSTS` 開 DNS-rebinding 保護；dev 預設關（會 log 警告）。

---

## 自己重跑
```bash
curl 'localhost:8002/search_apis?query=give a customer their money back'   # mode: hybrid
docker exec llm-wiki-pg psql -U wiki -d wiki -c "SELECT module,api_key FROM api_entries WHERE embed_text ILIKE '%money back%';"  # 關鍵字臂（可能 0 列）
curl 'localhost:8002/semantic_search?query=give%20a%20customer%20their%20money%20back&top_k=3'  # 語意臂 cosine
```
更多：[docs/api.md](api.md)、[docs/architecture/diagram.md](architecture/diagram.md)、
[docs/architecture/hybrid-knowledge-search.md](architecture/hybrid-knowledge-search.md)、
[docs/architecture/mcp-transport.md](architecture/mcp-transport.md)。
</content>
