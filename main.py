"""
main.py  —— メインループ（段取りだけを書く。処理は core/ の各モジュール）

研究計画の二段構成（9/22 MTG で合意）に対応しています。

┌─ 事前分析（人がコンフィグを決める・研究スコープに対して 1 回）─────────┐
│   9/2 回顧的インタビュー → アノテーション → config/*.yaml               │
│   ★ プログラムは実行しない。config/ を読むだけ                          │
│     インタビュー由来の値は config/*.yaml に【出典：事前分析＝9/2】と明記 │
└────────────────────────────────────────────────┘
┌─ メイン分析（LLM が自動で回す・作業者 N 人 × M サイクル）───────────┐
│  ① スコアリング                                                        │
│     ③ SOP–AO-OP 対応付け   core/align.py     LLM                       │
│     ④ step 観点ラベル付け   core/label.py     LLM                       │
│     ⑤ スコア合成           core/scoring.py   規則（モデルを呼ばない）   │
│        ↑ コンフィグとタスク固有の SOP・AO-OP が初めて統合される地点     │
│  ② 質問生成・対話                                                      │
│     ⑥ 質問・追問・自発的補足 core/dialogue.py  LLM ＋ 作業者            │
│     ⑦ 記録                   core/eventlog.py                          │
│     ⑧ 終止判定               セル枯渇 or 予算切れ                       │
│     ⑨ EKE-OP 出力            core/extract.py   LLM                     │
└────────────────────────────────────────────────┘

使い方:
  python main.py --only-scoring           ① スコアリングまでで止めて可視化する
  python main.py --mode sim               ①② を模擬作業者で 1 サイクル
  python main.py --mode real              実際の作業者が端末で回答
  python main.py --mode sim --cycles 2    2 サイクル回して継承を確認

出力（outputs/）:
  <run>_config.md       コンフィグの中身（出典つき）
  <run>_scoring.md      ① の結果。open セル上位と起点ごとの内訳
  <run>_scoring.html    ① の結果。step × プローブのヒートマップ
  <run>_dialogue.md     ② の対話記録（質問・回答・判定の全ターン）
  <run>_ekeop.json      最終成果物（対話記録も含む）
"""

import argparse ##使得python脚本可以像Linux terminal一样使用
import os
import sys
import unicodedata

from dotenv import load_dotenv

load_dotenv()          # 【ローカルファイル】.env から API_KEY 等を読む

from core import align as align_mod
from core import eventlog
from core import extract as extract_mod
from core import label as label_mod
from core import report
from core import scoring as scoring_mod
from core.dialogue import make_answerer, run_dialogue
from core.llm import LLM
from storage import store


def load_everything(aoop_name="aoop_v1"):
    """コンフィグ・入力を全部読む。【ローカルファイル】は store 経由のみ。

    aoop_name は data/<name>.json を指す。既定は aoop_v1（映像から記述できる
    内容のみを残した版）。v0（aoop）との比較は --aoop で切り替える。
    """
    return {
        # ── 事前分析の出力（コンフィグ）──
        "probes": store.load_config("probes"),
        "scoring": store.load_config("scoring"),
        "rubric": store.load_config("rubric"),
        "settings": store.load_config("settings"),
        # ── 当該ケースの入力 ──
        "sop": store.load_input("sop"),
        "aoop": store.load_input(aoop_name),
        "aoop_name": aoop_name,
    }


def show_config(cfg):
    """起動時に、事前分析（9/2 インタビュー）からどの値が来ているかを表示する。"""
    priors = scoring_mod.probe_priors(cfg["probes"])
    pp = cfg["probes"].get("probe_prior", {})
    P = cfg["probes"]["probes"]
    print(f"\n【事前分析の出力】 {pp.get('source', '')}")
    print(f"  プローブ優先度（数え方: {pp.get('basis')}）:")
    for k in sorted(P, key=lambda k: -priors[k]):
        print(f"    {_pad(P[k]['name_ja'], 14)} {priors[k]:>4}  {'■' * int(priors[k] * 5)}")
    print(f"  SOP 記述の根拠 → {', '.join(cfg['scoring']['sop_rationale_probes'])}")
    print(f"  閾値 min_cell_score = {cfg['scoring']['min_cell_score']}")


# ==================================================================
# メイン分析 ① スコアリング
# ==================================================================

def run_scoring(llm, run, cycle, cfg):
    """③→④→⑤。open セルを決めてイベントログに書き、行列を返す。"""
    print(f"\n{'='*60}\n  cycle {cycle} ── メイン分析 ① スコアリング\n{'='*60}")

    # ③ SOP と AO-OP の対応付け（前サイクルの結果を継承）
    prev_align = store.load_previous(run, cycle, "alignment")
    alignment = align_mod.run_alignment(
        llm, cfg["sop"], cfg["aoop"], prev_align, cfg["settings"])
    store.save_state(run, cycle, "alignment", alignment)
    print(f"③ 対応付け: {len(alignment['pairs'])} 組 / "
          f"未対応の SOP 項目 {len(alignment['unmatched_sop_items'])} 件")

    # ④ step ごとの観点ラベル付け（前サイクルの結果を継承）
    print(f"④ 観点ラベル付け中（{len(cfg['aoop']['steps'])} step、LLM を step 数だけ呼びます）…")
    prev_labels = store.load_previous(run, cycle, "labels")
    labels = label_mod.run_labeling(llm, cfg["aoop"], alignment, cfg["sop"], prev_labels)
    store.save_state(run, cycle, "labels", labels)

    # ⑤ スコア合成（規則計算。コンフィグ × SOP・AO-OP が統合される地点）
    print("⑤ スコア合成")
    matrix = scoring_mod.score_matrix(
        cfg["aoop"], alignment, labels, cfg["scoring"], cfg["probes"])
    store.save_state(run, cycle, "scores", matrix)
    cell_events = scoring_mod.build_cells(cycle, matrix)
    for ev in cell_events:
        store.append_event(run, cycle, ev)

    # 前サイクルで充分と判定したセルを引き継いで閉じる
    inherited = _inherit_closed(run, cycle, cell_events)

    n_open = len(cell_events)
    print(f"   open {n_open} / 全 {len(matrix['cells'])} セル"
          + (f"（うち前サイクルから引き継ぎ {inherited}）" if inherited else ""))
    _print_top_open(matrix, cfg["probes"])
    _warn_if_too_many(n_open - inherited, cfg["settings"]["dialogue"]["budget"])
    return matrix


def _inherit_closed(run, cycle, cell_events):
    """前サイクルで閉じたセルを今サイクルでも閉じる。聞き直しを防ぐ。"""
    if cycle <= 1:
        return 0
    prev_cov = eventlog.coverage(store.read_events(run, cycle - 1))
    opened = {(e["step"], e["probe"]) for e in cell_events}
    n = 0
    for key, v in prev_cov.items():
        sid, probe = key.split("|")
        if v["state"] == "closed" and (sid, probe) in opened:
            store.append_event(run, cycle, eventlog.make_event(
                cycle, "cell/closed", step=sid, probe=probe,
                terminal=v.get("terminal"), inherited=True))
            n += 1
    return n


def _print_top_open(matrix, probes_cfg, n=5):
    """open セルの上位を端末に出す。どの起点が押し上げたかも一緒に。"""
    P = probes_cfg["probes"]
    top = sorted([c for c in matrix["cells"] if c["status"] == "open"],
                 key=lambda c: -c["score"])[:n]
    if not top:
        return
    print(f"   上位 {len(top)} セル:")
    for c in top:
        parts = "  ".join(f"{scoring_mod.SOURCE_NAMES[k]}{v:g}"
                          for k, v in c["breakdown"].items() if v)
        print(f"     {c['step']:>5} × {_pad(P[c['probe']]['name_ja'], 14)} score={c['score']:<4}  ({parts})")


def _pad(text, width):
    """全角を 2 桁として数えて右を空白で埋める（端末表示の桁そろえ）。"""
    w = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(width - w, 0)


def _warn_if_too_many(n_open, budget):
    if n_open > budget * 2:
        print(f"   [注意] open {n_open} に対し予算 {budget}。全て問うには約 "
              f"{-(-n_open // budget)} サイクル必要。min_cell_score を上げて絞ることを検討")


# ==================================================================
# メイン分析 ② 質問生成・対話
# ==================================================================

def run_dialogue_phase(llm, run, cycle, cfg, mode):
    """⑥→⑨。対話を回し、EKE-OP を作って返す。"""
    print(f"\n{'='*60}\n  cycle {cycle} ── メイン分析 ② 質問生成・対話\n{'='*60}")

    answerer = make_answerer(mode, llm, cfg["settings"]["dialogue"]["free_input"])
    asked = run_dialogue(llm, run, cycle, cfg["aoop"], answerer, cfg)
    print(f"\n⑥ 質問数: {asked}")

    events = store.read_events(run, cycle)
    ekeop = extract_mod.build_ekeop(llm, cfg["aoop"], events, cfg["probes"], cfg["settings"])
    store.save_state(run, cycle, "ekeop", ekeop)

    s = ekeop["stats"]
    print(f"⑨ 知識項目 {s['knowledge_items']} 件 / unclassified {s['unclassified_items']} 件 / "
          f"出所不明 {s['untraceable_items']} 件")
    return ekeop, events


# ==================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default="run_001", help="実行 ID。runs/ 以下の名前になる")
    ap.add_argument("--cycles", type=int, default=1, help="サイクル数")
    ap.add_argument("--mode", default="sim", choices=["sim", "real"],
                    help="sim=LLM が作業者を演じる / real=人が端末で回答")
    ap.add_argument("--aoop", default="aoop_v1",
                    help="data/ 以下の AO-OP ファイル名（拡張子なし）。既定 aoop_v1")
    ap.add_argument("--only-scoring", action="store_true",
                    help="メイン分析 ① スコアリングまでで止め、結果を可視化する")
    args = ap.parse_args()

    key = os.getenv("API_KEY", "")
    if not key or key.startswith("sk-xxxx"):
        sys.exit("[ERROR] .env の API_KEY が未設定か、サンプル値のままです")

    cfg = load_everything(args.aoop)
    llm = LLM()
    print(f"model={llm.model}  temperature={llm.temperature}  "
          f"mode={args.mode}  run={args.run}")
    print(f"入力: data/{args.aoop}.json（{len(cfg['aoop']['steps'])} step）"
          f"　data/sop.json（{len(cfg['sop']['items'])} 項目）")
    llm.set_log_path(store.cycle_dir(args.run, 1) / "llm_calls.jsonl")
    show_config(cfg)

    priors = scoring_mod.probe_priors(cfg["probes"])
    store.save_text(f"{args.run}_config.md", report.config_md(cfg["probes"], cfg["scoring"], priors))
    actions = {s["step_id"]: s["action"] for s in cfg["aoop"]["steps"]}

    ekeop = None
    for c in range(1, args.cycles + 1):
        matrix = run_scoring(llm, args.run, c, cfg)
        store.save_text(f"{args.run}_scoring.md", report.scoring_md(matrix, cfg["probes"]))
        store.save_text(f"{args.run}_scoring.html",
                        report.scoring_html(matrix, cfg["probes"], args.run))
        if args.only_scoring:
            break

        ekeop, events = run_dialogue_phase(llm, args.run, c, cfg, args.mode)
        store.save_text(f"{args.run}_dialogue.md", report.dialogue_md(
            eventlog.dialogue_turns(events), cfg["probes"], cfg["rubric"], actions))

    print(f"\n{'='*60}\n  出力（outputs/）\n{'='*60}")
    print(f"  {args.run}_config.md       コンフィグ（出典つき）")
    print(f"  {args.run}_scoring.md      ① スコアリング結果")
    print(f"  {args.run}_scoring.html    ① ヒートマップ（ブラウザで開く）")
    if ekeop is not None:
        store.save_output(f"{args.run}_ekeop", ekeop)
        print(f"  {args.run}_dialogue.md     ② 対話記録")
        print(f"  {args.run}_ekeop.json      EKE-OP（対話記録を含む）")
    print(f"\nLLM 呼び出し {llm.calls} 回")


if __name__ == "__main__":
    main()
