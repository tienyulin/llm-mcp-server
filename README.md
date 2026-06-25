# mcp-server

> 👉 想看這個服務**實際怎麼運作（含真實紀錄）**：[docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md)。

LLM Wiki 平台的**唯讀查詢端（read-only query service）**。對 `wiki-processor` 建好的
wiki 提供關鍵字、語意、結構化查詢。**PG 優先（PG-first）**：關鍵字走 `pg_trgm`、
語意走 pgvector cosine；索引不可用時自動退回掃 MinIO `wiki.json`。內建記憶體 TTL
快取，可依 app 個別失效。

隸屬 [llm-wiki-mcp 平台](https://github.com/tienyulin/llm-wiki-mcp)，也可獨立部署。

> **名詞**
> - **MCP（Model Context Protocol）**：讓 AI agent 原生連外部工具的協議。本服務開 MCP 端點，Claude 直接連。
> - **hybrid search**：關鍵字 + 語意兩種搜尋用 RRF（倒數排名融合）合併，互補。
> - **PG-first / fallback**：先查 Postgres（快）；掛了退回掃 MinIO，查詢不整個壞掉。
> - **TTL 快取**：查過的結果暫存一段時間，重複查不用再撈。

## 架構
```
REST: GET /search_apis · /semantic_search · /list_apis · /get_api_detail · /wiki_info
            └─> PG/pgvector（快路徑）──退回──> MinIO wiki.json
      GET /list_concepts · /get_concept · /get_overview · /skill · /graph
      GET /list_knowledge · /get_knowledge · /search_knowledge
            └─> MinIO wiki.json（概念/總覽/知識，由 wiki-processor 建）
MCP:  POST /mcp/（Streamable HTTP，stateless 無狀態）—— 與 REST 同一套 QueryService，
            包成 MCP 工具讓 Claude/agent 原生連線
```
加進 Claude Code：`claude mcp add --transport http llm-wiki http://localhost:8002/mcp/`

- `http_api/` — FastAPI app + 路由（query、cache、health）+ 限流
- `services/` — query service、wiki service、embeddings（查詢端，含 query 向量 LRU 快取）、cache
- `repository/` — `minio_client.py`（讀）、`pg_reader.py`（唯讀，含斷路器 circuit breaker）
- `core/` — 設定 + 依賴注入

> **search_apis / search_knowledge 都是 hybrid**：PG + embedding 都在時跑關鍵字+語意
> 並用 RRF 融合，並有 cosine 相似度下限（`API_SEARCH_MIN_COSINE` / `MCP_KNOWLEDGE_MIN_COSINE`）
> 擋掉不相關結果；否則退回關鍵字。

## 快速開始
用**共用 infra**（[llm-wiki-infra](https://github.com/tienyulin/llm-wiki-infra)），讀的是
wiki-processor 寫入的同一套 MinIO + Postgres：
```bash
# 1) 共用 infra（一次）
(cd ../llm-wiki-infra && docker compose up -d)
# 2) 本服務
cp .env.example .env
docker compose up -d --build
curl localhost:8002/health
```
> mcp-server **只讀**。在同一 infra 上有 wiki-processor 把資料寫進 MinIO + PG 之前，查詢會回空。

## Dev Container（容器內開發）
本 repo 附 [`.devcontainer/`](.devcontainer/)。**先起共用 infra**，再於 VS Code /
Cursor：**Reopen in Container** —— 建置本服務、原始碼即時掛載於 `/app`、獨立 Python
環境、接上共用 `llm-wiki-net`。容器內：`python -m pytest`，或 `python http_api/main.py`
（:8002）。要有資料，請在同 infra 上跑一個 wiki-processor。

## 查詢範例
```bash
curl 'localhost:8002/list_apis'
curl 'localhost:8002/search_apis?query=billing'                       # hybrid
curl 'localhost:8002/semantic_search?query=charge%20a%20credit%20card&top_k=3'
curl 'localhost:8002/search_knowledge?query=undo%20a%20wrong%20DELETE' # 知識文件
curl 'localhost:8002/wiki_info'
```

## 設定
見 [`.env.example`](.env.example)。`EMBEDDING_*` 變數**必須與 wiki-processor 一致**
（同模型、同維度），查詢向量才會落在索引的同一空間。`QUERY_EMBED_CACHE` 設 query
向量快取大小。

## 測試
```bash
python -m pytest            # 隔離測試（MinIO SDK 被 stub）；需真 PG 的測試自動跳過
```

## 文件
- [架構圖](docs/architecture/diagram.md) — 分層 + PG 優先讀取路徑
- [hybrid 知識搜尋（含實測數據）](docs/architecture/hybrid-knowledge-search.md)
- [SAG 論文評估](docs/architecture/sag-evaluation.md)
- [API 參考](docs/api.md)
</content>
