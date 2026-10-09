# 個別科學研究：以蛻變測試與突變分析檢驗語音助理的自然語言意圖路由

受測對象是這個 repo 的 `jarvis/router.py`（語音助理的本機意圖路由，約 60 條 regex 規則）。
研究問題、方法、結果都在報告裡；這個目錄是**可以重跑的那一半**。

## 五分鐘看完

```bash
git clone https://github.com/Venshen885361/jarvis-desktop && cd jarvis-desktop
pip install -r requirements.txt            # 只需要核心套件；沒有麥克風、沒有 API 金鑰都能跑
python -m research.mt.demo                 # 約 1–2 分鐘：把報告每一節的數字重算一遍
python -m research.mt.demo --full          # 約 6–10 分鐘：突變測試跑全部 927 個突變體
```

`demo` 會先把 `research/mt/data/`（2026-09-14 的實驗快照：生成的測試句、Gemini 的 API 快取、人工標記）
複製到 `research/mt/out/`，所以 **LLM 的部分讀快取、不打 API**。想重新生成才需要 `GEMINI_API_KEY`。

## 每一步對應報告哪一節

| demo 的步驟 | 報告 | 看什麼 |
|---|---|---|
| 1 規則式生成 | 肆-一 RQ1 | 1,373 句、7 個違反（第一次跑是 433 個） |
| 2–4 四個溫度 + T=0 重跑兩次 | 肆-二 RQ2 | 每批 964 句、違反數 |
| 5 批次比較 | 肆-二 RQ2 | 溫度之間 vs 重跑之間的句子 / 錯集合 Jaccard |
| 6 人工標記 | 肆-一 RQ1 | 模型 96.5% / 規則式 91.5% 保留原意圖 |
| 7–8 突變矩陣、每批殺傷 | 肆-三 RQ3 | 突變分數、各批次殺掉幾個突變體 |
| 9 縮減與排序 | 肆-三 / 肆-四 | 196 條保留 100%、隨機 54%；additional APFD 0.985 |
| 10 存活突變體分類 | 肆-三 RQ3 | 60 個判斷各附一句 killer，程式驗證「殺 / 沒殺」 |
| 11 版本回歸 | 肆-五 RQ5 | 五個 git 版本的違反數（要在 git repo 裡跑） |

## 自己動手

| 想做的事 | 指令 |
|---|---|
| 看某批次的違反句 | `python -m research.mt.run --gen rules --show-violations` |
| 加一條種子句 | 編輯 `research/mt/seeds.json`（`expect` 用 `harness.route_label` 的字串格式），重跑 demo |
| 試一句話會被路由到哪 | `python -c "from research.mt.harness import route_label; print(route_label('記事本幫我打開'))"` |
| 看 router 的黃金測試（每類修正留一句） | `python -m pytest tests/test_router_golden.py -q` |
| 列出突變體 | `python -m research.mt.mutation --list` |
| 重新生成 LLM 批次（要金鑰） | `GEMINI_API_KEY=… python -m research.mt.run --gen llm --temperature 0.7 --no-cache` |

## 檔案

| 檔案 | 作用 |
|---|---|
| `mt/harness.py` | 把 router 變純函式：`route_label("幫我開一下記事本") → open_application:記事本` |
| `mt/relations.py` | 五條蛻變關係 |
| `mt/rules.py` / `mt/llm.py` | 模板生成器（對照組）/ Gemini 生成器（溫度可調、磁碟快取） |
| `mt/run.py` | 生成 → 過濾 → 路由 → 判定 → 報表 |
| `mt/compare.py` | 批次之間的 Jaccard、錯集合差 |
| `mt/mutation.py` | 七種針對 regex 的突變運算子、測試 × 突變體矩陣 |
| `mt/reduce.py` | 縮減（greedy / HGS / irreplaceable / 隨機）與排序（total / additional / 關係優先 / 隨機，APFD） |
| `mt/survivors.py` + `survivors_manual.json` | 存活突變體人工分類，每個判斷附可執行的 killer |
| `mt/versions.py` | 同一批測試跑在 router 的歷史版本上 |
| `mt/sample.py` | E1 抽樣、Cohen's κ、各生成器 precision |
| `mt/demo.py` | 以上全部一鍵重跑 |
| `mt/seeds.json` | 87 條種子（41 條原始 + 46 條從存活突變體反推的 killer） |
| `mt/data/` | 實驗快照（不含任何金鑰） |
| `mt/README.md` | 實驗日誌：每一輪的原因分類、修法、前後數字 |
| `PLAN.md` | 研究計畫：RQ、實驗、效度威脅、時程 |
| `../tests/test_router_golden.py` | 80 條黃金測試，CI 跑 |
| `../tests/test_mt_harness.py` | 測試工具自己的測試（harness、突變器、縮減、killer 驗證） |
