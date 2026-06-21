# 架構研究發現（第 2 輪）

全架構盤點：網路研究 + live 測試 + 自我質疑。供 reviewer（含其他模型）驗證。

> 注意：本文記錄當時（加入知識文件那輪）的結論。其中「單一 wiki.json + CAS 維持不變」
> 的判斷**後來被 P3 推翻**（改為每-app 物件）；詳見 wiki-processor 與
> [../../SCALE_STRESS_PLAN.md](../../SCALE_STRESS_PLAN.md)。保留原文供脈絡。

## 頭條改動：wiki 之前只裝 API

processor 之前只抽 **API endpoint**。Karpathy llm-wiki 的前提（也是我們的名字/目標）是
*通用*知識：LLM 把散文原始資料編譯成 agent 能推理的 summary/concept。我們把它窄化成只有
API spec，所以 wiki 答不出「FastAPI endpoint 怎麼寫？」或「Oracle Flashback 怎麼救資料？」。

**修法（簡單、加法式）**：新增 `knowledge` 文件型別。散文文件 → 結構化
`{title, summary, topics, key_points}` 存入 `wiki.knowledge`；API 不變。`doc_type` 自動
判斷（有 endpoint → api，否則 knowledge）。提到某概念 token 的知識文件會連到該概念 ——
橋接 knowledge ⇄ API。

**跨領域 live 實證。** 匯入真的 Oracle-Flashback + FastAPI-how-to 知識文件 + flashback-api
服務。透過 Claude over MCP 問 *"我誤刪資料（wrong DELETE）—— 怎麼救？有沒有內部 API？"*
模型回：技術 = Oracle Flashback（引 `oracle-kb:oracle-flashback`），內部 API =
`flashback-api POST /recover`（引 `flashback-api.md`）。抽象知識 → 具體服務，未經提示。

## 量測，而非假設

### CAS-at-scale（processor 最高風險問題）
對 live 單一 replica 做併發 `/process` burst：

| 模式 | N | 成功 | wall p50 |
|---|---|---|---|
| 不同 app | 50 | 50/50 | 29 ms |
| **同一 app（最大競爭）** | 50 | **50/50** | 474 ms |

單一 replica 從不耗盡 5 次 CAS 重試額度 —— in-process 寫鎖把 phase 2 序列化（每輪一個贏家）。
同一 app 競爭下的成本是**延遲，不是失敗**。**結論（當時）：單一 `wiki.json` + CAS 真相來源
在此規模夠用；不要改。** 待觀察：多 *replica* 同一 app burst（跨 process CAS）這裡沒測。
> （後續：P3 仍改成每-app 物件 —— 因為「寫入延遲隨 app 數成長」在更大規模才是真瓶頸。）

### MCP 接線
重新驗證上一輪加的原生 MCP server 仍正常可連；加了知識工具 + `knowledge://{doc_id}`
resource。研究確認 tools-vs-resources 分工（resource = 唯讀參考、tool = 動作）；我們兩者都做
—— tool 做檢索（Claude Code 用 tool 較可靠）、resource 做直接 grounding。

## 考慮後否決（保持簡單）

- **把單一 blob+CAS 換成每-app 物件 / DB 當真相來源** —— CAS 在規模下沒問題（已測）；改了
  增加複雜度而無實測收益。 *（註：P3 後來基於更大規模的寫入曲線證據改了。）*
- **無向量（PageIndex 式）取代 pgvector** —— pgvector 已能用且優雅降級；語料小且結構化。不改。
- **兩段式抽取** —— 保留；依來源 repo（nashsu/llm_wiki、VectifyAI/OpenKB）能實測降低
  single-pass 幻覺。

## 最高優先後續（不在這個 PR）

**把知識 index 進 pgvector。** 知識當時只有關鍵字可搜。live 跑時 `search_knowledge` 沒命中
模型第一個用詞，靠 `list_knowledge` 才救回。把知識條目 embed（重用既有 embedding + PG 路徑）
能讓 "wrong DELETE" 語意命中 flashback 文件。最高價值的下一步。
> （後續：已完成 —— 見 [hybrid-knowledge-search.md](hybrid-knowledge-search.md)。）

## 怎麼驗證

```bash
# 起 stack；匯入一份知識文件 + 一個 api 服務；重建概念
curl -s "localhost:8002/search_knowledge?query=data%20loss"      # → oracle flashback 文件
curl -s "localhost:8002/get_concept?name=recover"                # → 連結 knowledge + flashback-api
# 透過 Claude：
claude mcp add --transport http llm-wiki http://localhost:8002/mcp/
claude -p "I had accidental data loss — how to recover, any internal API?" \
  --allowedTools mcp__llm-wiki__search_knowledge mcp__llm-wiki__get_knowledge \
                 mcp__llm-wiki__search_apis mcp__llm-wiki__get_api_detail
```
</content>
