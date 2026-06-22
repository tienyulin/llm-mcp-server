# 為什麼要做原生 MCP server（Streamable HTTP）

> 名詞：**MCP（Model Context Protocol）** = 讓 AI agent 原生連外部工具的協議；
> **transport** = 連線方式；**stdio** = 走本機標準輸入/輸出（只能本機跑）；
> **Streamable HTTP** = 一個 HTTP 端點、可多人連、可水平擴展。

## 缺口

這個專案以 MCP 命名、前提是「LLM 來消費這份 wiki」，但服務一直以來只會講 **REST**。
曾經有過一個 MCP **stdio** server，但被刻意移除（commit `0f25439`，*"simplify
mcp-server to HTTP API only, remove stdio version"*）—— 因為 stdio 無法團隊部署：
每個使用者得各自跑一個本機 process。所以 agent 沒辦法照「名字承諾的方式」連到這份
共用 wiki，只能自己寫一個客製 REST client。

## MCP 改變了什麼

2024 年的選擇是二選一：**stdio**（本機、不可部署）或什麼都沒有。MCP 規格
（2025-03-26）新增 **Streamable HTTP** transport —— 單一 HTTP 端點，支援多個並發
client、水平擴展、OAuth，是遠端 server 的建議 transport。這化解了原本的取捨：
一個 HTTP server，團隊能部署，agent 也能原生連。

## 決策

把 MCP 重新加回來，做成**既有 `QueryService` 之上的薄工具層**（與 REST 同一套邏輯），
掛在既有 FastAPI app 的 `/mcp`（實際端點 `POST /mcp/`）。不開第二個服務、不加新基礎
設施、不加新相依（`mcp` 本來就在相依清單）。REST 留給網頁/團隊介面與
`/cache/invalidate` callback；MCP 服務 agent。

**無狀態**（`stateless_http=True`）：每個請求自包含，所以這個唯讀 server 可掛在負載
平衡後水平擴展、無 session 黏滯 —— 對齊 MCP 2026 的無狀態運作路線。

## 考慮過但否決的替代方案

- **只留 REST + `/skill` 匯出。** `/skill` 把 wiki 打包成**靜態** Anthropic Skill。
  做分發可以，但兩次重建之間會過期；MCP 提供對當前 wiki 的即時查詢。兩個都留 —— 分工不同。
- **重新加回 stdio。** 同樣的不可部署問題。對共用、團隊部署的 wiki，Streamable HTTP 完勝。
- **更大的架構改動**（換掉單一 `wiki.json`+CAS 真相來源；把 pgvector 換成無向量檢索）。
  考慮後否決：以目前規模兩者都夠用，改了只增加複雜度、收益小。MCP 缺口才是高價值、
  低複雜度、切題的勝點。

## 接線筆記（不直覺，靠測試才發現）

- 官方 SDK（`mcp>=1.3.0`）的 `FastMCP(...).streamable_http_app()` → Starlette app
  （這**不是** 另一個 FastMCP v2 的 `http_app()`）。
- Starlette **不會**自動跑被掛載 sub-app 的 lifespan。MCP session manager 必須把
  `mcp_app.router.lifespan_context(mcp_app)` 提升到父 FastAPI lifespan 裡啟動，否則：
  *"Task group is not initialized."*
- session manager **每個 instance 只能跑一次**；反覆進出 lifespan 的測試每次要建新的
  `create_app()`。
- 設 `streamable_http_path="/"`，掛在 `/mcp` 才會剛好是 `/mcp/`（否則內層 route 變成 `/mcp/mcp`）。
- DNS-rebinding 保護會擋未知 `Host` header（HTTP 421）。正式環境設 `MCP_ALLOWED_HOSTS`。

## 怎麼驗證

```bash
# 1. 起 infra + wiki-processor + mcp-server，push 一個 app 到 :8001/process
# 2. 用 HTTP 做 handshake + 呼叫工具：
curl -s -X POST localhost:8002/mcp/ \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}'
# → serverInfo.name == "llm-wiki"
# tools/list → 工具清單；tools/call get_api_detail → 含 sources[] + 出處的條目
```
自動化：`tests/test_mcp_server.py`（initialize → tools/list → tools/call）。
</content>
