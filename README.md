# EKE-OP 生成パイプライン

AO-OP（映像から生成された動作観察手順書）を起点に、CTA の観点空間に沿って
作業者と対話し、EKE-OP（熟練知拡充作業手順書）を生成する。

研究計画「研究具体方案 2026-9-9」の処理順序①〜⑨に対応。⑩評価は未実装。

---

## 使い方

```bash
pip install -r requirements.txt
cp .env.example .env          # API_KEY を書く

python main.py --only-scoring          # ① スコアリングまでで止めて可視化（研究会用）
python main.py --mode sim              # ①② を模擬作業者で 1 サイクル
python main.py --mode real             # 実際の作業者が端末で回答
python main.py --mode sim --cycles 2   # 2 サイクル回して継承を確認
```

## 出力（outputs/）

| ファイル | 中身 |
|---|---|
| `<run>_config.md` | コンフィグの中身。各値の出典（9/2／CTA一般／設計判断）つき |
| `<run>_scoring.md` | ① スコアリング結果。open セル上位と、五つの起点ごとの内訳 |
| `<run>_scoring.html` | ① step × プローブのヒートマップ。ブラウザで開いてスライドに貼る |
| `<run>_dialogue.md` | ② 対話記録。質問・回答・3 軸判定を全ターン |
| `<run>_ekeop.json` | 最終成果物。`dialogue` に対話記録も含む |

## 二段構成との対応（9/22 MTG）

- **事前分析**（人・1 回）= `config/*.yaml` を決めること。プログラムは実行しない
- **メイン分析 ① スコアリング** = `align.py` → `label.py` → `scoring.py`
- **メイン分析 ② 質問生成・対話** = `dialogue.py` → `extract.py`

## 9/2 インタビューの結果がコードに入る場所

`config/*.yaml` の各ブロックに `【出典：事前分析＝9/2】` と書いてある箇所がすべて。

| 場所 | 中身 | 効き方 |
|---|---|---|
| `probes.yaml` の `probe_prior` | 各プローブの該当件数（58 項目のアノテーション） | 優先度として全 step に加算 |
| `probes.yaml` の `interview_example` | 各プローブで実際に出た答えの例 | 質問生成プロンプトに参考として渡す |
| `scoring.yaml` の `sop_rationale_probes` | 「SOP 記述の根拠」起点 | 対応 SOP 項目がある step に加点 |
| `settings.yaml` の `free_input` | 自発的補足の奨励文言（22/58 件＝38%） | 対話中に毎ターン表示 |
| `settings.yaml` の `closing_questions` | 終盤の開放質問（1 問で枠外 3 件） | 対話の最後に固定で置く |
| `rubric.yaml` の `terminal_states` | 「理由なし」等の終止状態（04・06・07） | 追問の空転を止める |

---

## ★ 人が直す四箇所

コードを読まずに挙動を変えたいとき、触るのはここだけです。

| 場所 | 中身 | いつ直すか |
|---|---|---|
| `config/*.yaml` | **判断基準そのもの**。8 観点の定義、起点→観点の対応表、3 軸ルーブリック | 研究の貢献物。定義文書と同じ内容をここに書く |
| `prompts/*.txt` | 5 つのプロンプト雛形 | 質問の言い回し、出力形式を変えたいとき |
| `core/llm.py` | **モデルを呼ぶ唯一の場所** | モデル差し替え、温度調整 |
| `storage/store.py` | **ローカルファイルを触る唯一の場所** | 保存場所・ファイル名の変更 |

---

## ディレクトリ

```
config/     判断基準（設計時に一度決める。実行時には動かない）
  probes.yaml    8 観点の定義と質問方向
  scoring.yaml   起点→観点の対応表、重み
  rubric.yaml    深さ判定の 3 軸と終止状態
  settings.yaml  予算・追問上限・自発発話の文言

prompts/    プロンプト雛形（コードから分離してある）

core/       処理。研究計画の番号と 1 対 1
  llm.py        モデル呼び出し
  eventlog.py   イベントログと投影（カバレッジ行列はここから計算）
  align.py      ③ SOP–AO-OP 対照
  label.py      ④ step 観点ラベル付け
  scoring.py    ⑤ スコア合成・セル選択（モデルを呼ばない）
  dialogue.py   ⑥ 質問・追問・自発発話
  extract.py    ⑨ 知識抽出・EKE-OP 生成

storage/    ファイル入出力
data/       入力（読み取り専用）: sop.json, aoop.json
runs/       サイクルごとの途中経過（消して再実行してよい）
outputs/    成果物
```

---

## 設計上の約束

**イベントログが唯一の真実源**
カバレッジ行列は変数として持たず、`events.jsonl` から毎回投影する。
任意の時点の状態を復元できる。なぜその質問をしたか説明できる。途中で落ちても再開できる。

**AO-OP は書き換えない**
入力は読み取り専用。EKE-OP は別物として作る。書き換えると出所を辿れなくなる。

**LLM は意味を、規則は字面を判定する**
`label.py` に渡すのは `action` テキストのみ。`on_failure` 等のフィールドは
`scoring.py` の「記述密度」だけが見る。両方に見せると同じ根拠を二重に数える。

**8 観点に収まらない知識は捨てない**
`unclassified` に入れる。9/2 のパイロットでは 15 件・9 類型が該当した。
固定スキーマに押し込むと、知識は残るが「何の類型か」という情報が消える。

**「理由なし」は浅い回答ではなく到達点**
`rubric.yaml` の `terminal_states`。区別せずに追問すると空転する。
出力にも状態を残す。「問ったが理由が無い」と「まだ問っていない」は別物。

**作業者の自発発話は予算を消費しない**
9/2 では知識の 22/58 件（38%）がこの経路だった。
`settings.yaml` の `free_input` を消すと、この 38% が丸ごと落ちる。

---

## 出力の読み方

`outputs/<run>_ekeop.json`

- `steps[].knowledge[]` — 観点ごとの知識項目
- `unclassified[]` — 8 観点に収まらなかったもの。`note` に収まらない理由
- `coverage` — セルごとの `open` / `probed` / `closed` と終止状態
- `stats.untraceable_items` — **転写に出所が見つからない項目の数＝幻覚の疑い**

`untraceable_items` が 0 でない場合、抽出段階で発言に無いことが書かれている。
評価指標として報告する値でもある。

---

## 未実装（研究計画 第 10 節）

評価モジュール。人間基線カバレッジ率、幻覚率、作業者検閲の修正率、
LLM-as-a-Judge（判定モデルは生成モデルと別系列にすること）。
ルーブリックは `config/rubric.yaml` をそのまま使い回せる設計にしてある。
