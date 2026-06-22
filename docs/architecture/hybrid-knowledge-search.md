# Hybrid 知識搜尋（含實證）

修掉上一輪指出的「知識檢索只有關鍵字」問題：改寫過的問法（「undo a wrong DELETE」）
因為字面沒重疊，找不到 Oracle flashback 文件。

> 名詞：**RRF（Reciprocal Rank Fusion，倒數排名融合）** = 只看排名、不看分數尺度地把
> 兩份結果合併；**BM25** = 經典關鍵字排序演算法；**NDCG / recall** = 檢索品質指標；
> **cosine** = 向量相似度。

## 為什麼是 hybrid，而不是「加個向量搜尋就好」

2026 RAG benchmark：**純向量 ≈ 純關鍵字**（WANDS NDCG 0.695 vs 0.698）—— 單獨加向量
**不會**穩定贏過既有的關鍵字搜尋。贏點在**融合**：hybrid 79% vs BM25 58% 檢索準確率；
RRF 比任一單獨高 +7.4% NDCG。
來源：[Digital Applied](https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026)、
[buildmvpfast](https://www.buildmvpfast.com/blog/hybrid-search-rag-vector-keyword-reranking-2026)。

所以我們用 **RRF** 融合向量 + 關鍵字（只看排名 → 沒有分數尺度不相容問題）。

## 設計

- `knowledge_entries` 表（與 `api_entries` 分開 → API 路徑可證明未受影響）：向量 HNSW
  + trigram GIN 索引。與 API 同一套 embedding pipeline。
- processor 在匯入時把每份知識的精煉文字（title|summary|topics|key_points）embed
  —— 短文件就是一個聚焦的「chunk」。
- `pg_reader.hybrid_search_knowledge`：向量 top-20 ∪ trigram top-20，用 RRF 融合。
- `search_knowledge` 在 PG+embedding 在時為 hybrid，否則退回關鍵字 —— 與
  `semantic_search` 同樣的優雅降級契約。

## 相關性下限（量測得來，非猜的）

向量搜尋一定會回最近鄰，所以不相關問句也會回一份文件。實測 cosine
（bge-small-en-v1.5）於本語料：

| 問句 | cosine |
|---|---|
| 相關改寫（5 句） | 0.615 – 0.695 |
| 不相關（bake bread / weather / shoes） | 0.365 – 0.452 |

明顯落差 → 下限 **0.5**（環境變數 `MCP_KNOWLEDGE_MIN_COSINE`）。低於它就丟掉向量側；
不相關問句回空。

## 結果（live，真 embedding）

本地 bge-small embedding server、真實匯入。flashback 文件的召回：

| 問句 | keyword | hybrid |
|---|---|---|
| data loss | ✓ | ✓ |
| point in time recovery | ✗ | ✓ |
| undo a wrong DELETE | ✗ | ✓ |
| restore lost rows | ✗ | ✓ |
| revert accidental changes | ✗ | ✓ |
| roll back a mistaken update | ✗ | ✓ |
| **召回率** | **1/6** | **6/6** |
| how to bake bread（負例） | ✗ | ✗（正確回空） |

透過 Claude over MCP，*"a teammate fat-fingered a DELETE and rows are gone"* →
`search_knowledge` **mode hybrid** → Oracle flashback 文件 + `flashback-api POST
/recover`，附出處。字面零重疊。

## 怎麼重現

```bash
# 真本地 embedding（免 key）：fastembed bge-small 跑在共用網路上
# 把 stack 指過去：EMBEDDING_BASE_URL=http://embed-srv:8088 EMBEDDING_DIM=384 MOCK_EMBEDDINGS=false
# 匯入一份知識文件 + 一個 api 服務，然後：
curl -s "localhost:8002/search_knowledge?query=undo%20a%20wrong%20DELETE"   # mode: hybrid，命中 flashback
curl -s "localhost:8002/search_knowledge?query=how%20to%20bake%20bread"     # mode: keyword_fallback，空
```

## 後續（已完成）—— 延伸到 API 搜尋

同樣的 hybrid + 下限套用到 **API** 搜尋。`search_apis` 現在也是 hybrid（同一套 RRF，
跑在既有 `api_entries` 向量 + trigram 索引上；`API_SEARCH_MIN_COSINE` 下限）。
**reranking 評估後跳過** —— 2026 指引：reranking 在第一階段很雜或語料很大時才有用；
我們語料小、hybrid 已能回對答案，加 reranker 只增延遲、無益。

實證 —— `/recover` 在改寫問句的召回（真 bge-small）：

| 問句 | keyword | hybrid |
|---|---|---|
| recover / flashback recovery | ✓ | ✓ |
| undo deleted rows | ✗ | ✓ |
| roll back a table | ✗ | ✓ |
| restore lost data | ✗ | ✓ |
| revert a bad write | ✗ | ✓ |
| **召回率** | **2/6** | **6/6** |
| how to bake bread（負例） | ✗ | ✗（0 筆） |
</content>
