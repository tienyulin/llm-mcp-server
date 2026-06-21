# 評估：SAG（query-time 動態 hyperedge）vs. 我們的設計

論文：[SAG: SQL-Retrieval Augmented Generation with Query-Time Dynamic
Hyperedges](https://arxiv.org/abs/2606.15971)。當成候選改進評估。
**結論：不整套採用；之後借一個概念就好。**

> 名詞：**hyperedge（超邊）** = 一條邊連多個節點；**multi-hop** = 跨多筆資料串接推理；
> **agentic** = 由 AI agent 主導、可多次呼叫工具；**GraphRAG/HippoRAG** = 預先建知識圖的 RAG 法。

## SAG 在做什麼

每個 chunk → 一個 *event* + LLM 抽出的 *索引 entity*（11 種）。表：events、entities、
event–entity 關聯表。查詢時用 SQL join 把「共用 entity 的 events」串成*局部 hyperedge*，
沿 entity frontier 擴展 ≤H 跳，排序，回傳 chunks。append-only、不預建全域圖。
在 multi-hop QA 上勝過 HippoRAG 2（MuSiQue R@2 64.1 vs 49.5；HotpotQA 91.6 vs 78.4）。

## 它為何在它的場景贏 —— 而那場景不是我們的

SAG 針對的是 **非 agentic、單次 RAG** 跑在**大型 multi-hop 語料**上（HotpotQA/MuSiQue、
「上億筆」）。它的收益來自把 multi-hop 串接烤進一次檢索，以及省掉靜態知識圖
（GraphRAG/HippoRAG）的重建成本。

我們的系統在兩個軸上都不同：

1. **我們是 agentic。** MCP agent 用**連續呼叫工具**做 multi-hop —— 已經取代了 SAG 的
   query-time frontier 擴展。
2. **小語料。** SAG 相對預建圖的增量/規模優勢在這裡很邊際；我們的 `rebuild_concepts` 很便宜。
3. **simple-but-powerful 約束。** 完整 SAG = MySQL + Elasticsearch + LLM 11 型 entity
   抽取 + query-time join/rerank 引擎。對我們的目標來說面積太大。

## 實證：agent 本來就在做 SAG 式的 multi-hop

設定：3 份知識文件構成 2 跳鏈 + flashback-api 服務。runbook 只說「用資料庫的 recovery
能力…回溯到某個時間點」—— **完全沒提** flashback 或 `/recover`。問句：*"production
incident，一張表掉了資料 —— runbook 步驟 + 確切的內部 API。"*

agent 答對了。它自己的 trace：

```
search_knowledge(...)  → runbook + oracle-flashback 文件
get_knowledge(runbook) → "recovery capability"（抽象，單看是死路）
get_knowledge(oracle)  → FLASHBACK TABLE（SQL，不是 API）
list_concepts()        → 概念 "recover" 橫跨 [flashback-api, oracle-kb, runbook-kb]
get_concept("recover") → related: flashback-api::POST /recover  ← 這就是 join
get_api_detail(...)    → POST /recover 確認
```

從 runbook 散文連到實際 endpoint 的橋，就是**我們的 `concepts` 層** —— 一個跨領域連結
events 的概念**本身就是一條 hyperedge**，agent 走過了它。`search_apis("flashback")`
回 `[]`；扛起 multi-hop 的是概念 hyperedge，不是關鍵字搜尋。

**結論：** SAG 烤進檢索的東西，我們用（概念 hyperedge + agentic 連續工具呼叫）以遠少的
machinery 就達成了，且符合我們的規模。

## 唯一值得借的概念（之後、可選）

我們的概念連結是**字面子字串**式（一筆資料要文字裡literally含 "recover" 才連到 `recover`
概念）。這很脆：只寫 "roll back"/"undo" 的文件不會被連到，即使 hybrid *搜尋*已能靠
embedding 找到它。SAG 的啟示：連結要從**語意**推導，不是字串比對。

便宜、符合現況的升級（不加新基礎設施 —— 已有 embedding + pgvector）：用 **embedding
鄰近度**（或輕量 LLM 標籤）建概念/entity 連結，而非子字串，讓 hyperedge 對同義詞穩健。
這是把 SAG 的洞見蒸餾到我們的規模；SAG 其餘部分都與我們的 agent loop 重複。

> **後續**：此「語意概念連結」已實作（見 wiki-processor 的
> `docs/architecture/semantic-concept-linking.md`），用 dominant-app 邊界擋掉泛用文件的誤連。

**脆弱性的實測。** 匯入一份純用同義詞的文件（`syn-kb:undo-guide`）—— 只有 "roll back"、
"undo"、"revert"，從不出現 "recover"：

| 層 | 用 recovery 問句找得到 `syn-kb`？ |
|---|---|
| 概念連結（`get_concept "recover"`） | **否** —— 沒連到（子字串沒命中） |
| hybrid `search_knowledge("recover lost data")` | **是** —— mode hybrid，回傳它 |

搜尋層已對同義詞穩健（hybrid embedding）；只有*概念連結*層字面脆弱。那 —— 也只有那 ——
才是 SAG「靠語意連結」能補強的地方（agent 做 multi-hop 時靠它）。

## 建議

- **拒絕**完整 SAG（query-time SQL hyperedge 引擎、11 型 entity store、ES+MySQL）：與
  agentic 連續工具呼叫重複，對我們語料過度設計。
- **列入待辦**一項：把概念連結改成語意（embedding）式，而非子字串，強化 agent 依賴的
  跨領域 hyperedge。（已完成，見上方後續。）
- 架構維持：`concepts` + hybrid 知識搜尋 + agentic MCP。
</content>
