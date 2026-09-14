# 蛻變測試 × 自然語言意圖路由（個別科學研究用）

受測對象：`jarvis/router.py` —— 用正規表達式把一句話送到「開程式 / 播音樂 / 家電 / 純問答 / 交給模型」。
輸入是自然語言，沒有 oracle（沒人能列出所有句子的正確答案），所以用**蛻變關係**當判準：

| 關係 | 改寫方式 | 路由應該 |
|---|---|---|
| R1 同義改寫 | 打開 → 開啟 / 啟動 / 幫我開 | 相同 |
| R2 語助詞 | 幫我…一下 / …好嗎 | 相同 |
| R3 換語序 | 記事本幫我開一下 | 相同 |
| R4 無關前綴 | 欸、那個、JARVIS | 相同 |
| R5 近似句 | 不要打開記事本 / 記事本打不開怎麼辦 | **不同**（不該觸發） |

兩個生成器照同一份關係生：`rules.py`（模板，對照組）與 `llm.py`（Gemini，溫度是實驗變因）。

## 跑

```bash
pip install -e ".[gemini]"                       # 只要 google-genai
python -m research.mt.run --gen rules --show-violations
python -m research.mt.run --gen llm --model gemini-3.5-flash-lite --temperature 0 0.3 0.7 1.0 --n 5
```

輸出在 `research/mt/out/`（不進 git）：`tests_<tag>.jsonl` 每條測試一行、`summary_<tag>.json` 各關係統計、`cache/` API 快取。

指標：`valid%`（過濾後留下的比例 = 語意沒漂移）、`viol%`（違反關係 = 路由的錯）、`dist2`（字元 bigram 多樣性）。

## 第一次規則式結果（2026-09-14，router @ 5065037）

| 關係 | 生成 | 違反率 | 代表案例 |
|---|---|---|---|
| R1 同義 | 48 | 14.6% | 「開github.com」走 open_application 而不是 open_url |
| R2 語助詞 | 288 | 48.6% | 「打開記事本好嗎」→ 目標變成「記事本好嗎」 |
| R3 換語序 | 52 | 96.2% | 「記事本幫我打開」→ 交給模型；「下載資料夾幫我打開」→ 變成安裝程式 |
| R4 前綴 | 288 | 41.0% | 「欸 開 YouTube」→ 交給模型（`_BARE_OPEN` 只認句首） |
| R5 近似句 | 252 | 46.8% | 「不要打開記事本」**真的會打開記事本** |

一次跑一秒，928 句，找到 433 個違反——全部是手寫測試沒抓到的。

## 檔案

| 檔案 | 作用 |
|---|---|
| `harness.py` | 把 router 變純函式：`route_label("幫我開一下記事本") → Label('open_application','記事本')`；所有出口換成記錄器 |
| `relations.py` | 五條蛻變關係的定義（兩個生成器共用） |
| `rules.py` | 模板生成器（對照組） |
| `llm.py` | Gemini 生成器：溫度可調、JSON 輸出、磁碟快取、失敗如實記錄 |
| `run.py` | 生成 → 過濾 → 路由 → 判定 → 報表 |
| `seeds.json` | 36 條種子句與期望路由 |
| `../../tests/test_mt_harness.py` | 煙霧測試（CI 跑） |

## 下一步（研究計畫）

1. LLM 生成掃四個溫度，跟規則式比 valid% / viol% / dist2。
2. `mutmut` 對 `router.py` 做突變 → 測試 × 突變體矩陣 → 縮減（coverage / greedy / irreplaceable）與排序（APFD）。
3. 把 R5 找到的真 bug（否定句、語序）修回 router，重跑驗證。
