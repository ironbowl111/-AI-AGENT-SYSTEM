"""
core/report.py  —— 可視化レポート

★ このファイルはモデルを呼びません。ログと設定を人が読める形にするだけです。

出力（すべて outputs/ に置かれる。ファイルの書き込みは storage/store.py 経由）:

  <run>_config.md         コンフィグの中身。どの値が 9/2 インタビュー由来かを明示
  <run>_scoring.md        メイン分析①の結果。open セルの上位と、その内訳
  <run>_scoring.html      step × プローブのヒートマップ。スライドにそのまま貼れる
  <run>_dialogue.md       メイン分析②の対話記録。質問・回答・判定を全ターン
"""

import html

from core.scoring import SOURCES, SOURCE_NAMES


# ==================================================================
# 1. コンフィグ
# ==================================================================

def config_md(probes_cfg, scoring_cfg, priors):
    """probes.yaml / scoring.yaml の中身を、出典つきで表にする。"""
    P = probes_cfg["probes"]
    pp = probes_cfg.get("probe_prior", {})
    basis = pp.get("basis", "all_mentions")
    counts = pp.get("counts", {})
    w = scoring_cfg["weights"]

    out = ["# コンフィグ（事前分析の出力）\n",
           "メイン分析はこのコンフィグを読むだけで、書き換えない。",
           "各値の出典: **【9/2】** = 回顧的インタビューの分析結果 ／ "
           "**【CTA】** = CTA 一般の定義 ／ **【設計】** = 設計判断\n"]

    # --- プローブ優先度
    out += [f"## 1. プローブの優先度 【9/2】\n",
            f"出典: {pp.get('source', '—')}　使用する数え方: `{basis}`\n",
            f"優先度 = 2 × 件数 ÷ 最大件数（0〜2）。全 step に一律に加算される。\n",
            "| プローブ | 全言及 | 単独のみ | 質問起点 | **優先度** |",
            "|---|---:|---:|---:|---:|"]
    for k in sorted(P, key=lambda k: -priors[k]):
        c = [counts.get(b, {}).get(k, 0) for b in ("all_mentions", "single_only", "question_driven")]
        out.append(f"| {P[k]['name_ja']}（{k}） | {c[0]} | {c[1]} | {c[2]} | **{priors[k]}** |")

    # --- プローブ定義
    out += ["\n## 2. プローブの定義\n",
            "| プローブ | 質問方向 【CTA】 | 9/2 で実際に出た答え 【9/2】 |",
            "|---|---|---|"]
    for k, v in P.items():
        out.append(f"| {v['name_ja']} | {v['direction']} | {v.get('interview_example', '—')} |")

    # --- スコア式
    out += ["\n## 3. スコアの式 【設計】\n",
            f"セルのスコア ＝ Σ（起点 × 重み）。**{scoring_cfg.get('min_cell_score')} 以上で open**。\n",
            "| 起点 | 重み | 出典 | 中身 |", "|---|---:|---|---|",
            f"| 事前分析の優先度 | {w.get('prior', 0)} | 【9/2】 | 上の表 |",
            f"| LLM の観点ラベル | {w['label']} | メイン分析④ | step ごとに LLM が 0〜2 を付ける |",
            f"| SOP 記述の根拠 | {w['sop_rationale']} | 【9/2】 | 対応 SOP 項目があれば "
            f"{', '.join(scoring_cfg.get('sop_rationale_probes', []))} に加点 |",
            f"| SOP 差分 | {w['relation']} | 【設計】 | 関係の種類ごとに下表の観点に加点 |",
            f"| 記述密度 | {w['density']} | 【設計】 | AO-OP の欄が空なら対応する観点に加点 |"]

    out += ["\n### SOP 差分 → 押し上げる観点\n", "| 関係 | 観点 |", "|---|---|"]
    for rel, ps in scoring_cfg["relation_to_probes"].items():
        out.append(f"| {rel} | {', '.join(ps) or '（なし）'} |")

    out += ["\n### 記述密度 → 押し上げる観点\n", "| AO-OP の欄 | 観点 |", "|---|---|"]
    for f, p in scoring_cfg["field_to_probe"].items():
        out.append(f"| `{f}` | {p} |")

    return "\n".join(out) + "\n"


# ==================================================================
# 2. スコアリング結果
# ==================================================================

def scoring_md(matrix, probes_cfg, top_n=15):
    """メイン分析①の結果。open の上位を、どの起点が押し上げたかと一緒に示す。"""
    P = probes_cfg["probes"]
    cells = matrix["cells"]
    thr = matrix["threshold"]
    opened = sorted([c for c in cells if c["status"] == "open"],
                    key=lambda c: (-c["score"], c["step"]))

    steps = sorted({c["step"] for c in cells}, key=_step_key)
    out = ["# メイン分析 ① スコアリング結果\n",
           f"- セル総数: {len(cells)}（{len(steps)} step × {len(P)} プローブ）",
           f"- **open（要質問）: {len(opened)}**　／　skip: {len(cells) - len(opened)}",
           f"- 閾値: スコア {thr} 以上を open\n"]

    # 記述密度の自動判定
    out += ["## 記述密度シグナルの有効／無効\n", "| 欄 | 充足率 | 状態 |", "|---|---:|---|"]
    for d in matrix["density"]:
        out.append(f"| `{d['field']}` | {d['fill_rate']:.0%} | "
                   f"{'有効' if d['active'] else '**無効**（全 step ほぼ一律）'} |")

    # open の上位
    head = " | ".join(SOURCE_NAMES[s] for s in SOURCES)
    out += [f"\n## open セルの上位 {min(top_n, len(opened))} 件\n",
            "スコアが高い順。右側の列が、各起点がどれだけ押し上げたかの内訳。\n",
            f"| step | 工程 | プローブ | **score** | {head} |",
            "|---|---|---|---:|" + "---:|" * len(SOURCES)]
    for c in opened[:top_n]:
        b = " | ".join(_fmt(c["breakdown"][s]) for s in SOURCES)
        out.append(f"| {c['step']} | {_short(c['action'])} | {P[c['probe']]['name_ja']} | "
                   f"**{c['score']}** | {b} |")

    # プローブ別の open 数
    out += ["\n## プローブ別の open 数\n", "| プローブ | open |", "|---|---:|"]
    for k in P:
        n = sum(1 for c in opened if c["probe"] == k)
        out.append(f"| {P[k]['name_ja']} | {n} |")

    return "\n".join(out) + "\n"


def scoring_html(matrix, probes_cfg, run):
    """step × プローブのヒートマップ。色 = スコア、太枠 = open。"""
    P = probes_cfg["probes"]
    cells = {(c["step"], c["probe"]): c for c in matrix["cells"]}
    steps = sorted({c["step"] for c in matrix["cells"]}, key=_step_key)
    actions = {c["step"]: c["action"] for c in matrix["cells"]}
    top = max((c["score"] for c in matrix["cells"]), default=1) or 1
    thr = matrix["threshold"]
    n_open = sum(1 for c in matrix["cells"] if c["status"] == "open")

    rows = []
    for s in steps:
        tds = []
        for p in P:
            c = cells[(s, p)]
            tip = f"{P[p]['name_ja']} score={c['score']}\n" + "\n".join(
                f"{SOURCE_NAMES[k]}: {c['breakdown'][k]}" for k in SOURCES if c["breakdown"][k])
            cls = "open" if c["status"] == "open" else "skip"
            tds.append(f'<td class="{cls}" style="background:{_color(c["score"], top)}" '
                       f'title="{html.escape(tip)}">{c["score"]:g}</td>')
        rows.append(f'<tr><th class="st">{s}</th><td class="act">{html.escape(actions[s])}</td>'
                    + "".join(tds) + "</tr>")

    head = "".join(f'<th class="pr">{P[p]["name_ja"]}<small>{p}</small></th>' for p in P)
    return f"""<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>スコアリング結果 {html.escape(run)}</title>
<style>
  body {{ font-family: "Hiragino Sans","Yu Gothic",sans-serif; margin: 24px; color:#1a1a1a; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .sub {{ color:#555; font-size: 13px; margin-bottom: 16px; }}
  table {{ border-collapse: collapse; font-size: 12px; }}
  th, td {{ border: 1px solid #ddd; padding: 4px 6px; }}
  th.pr {{ width: 58px; font-size: 11px; line-height: 1.25; background:#fafafa; font-weight: 600; }}
  th.pr small {{ display:block; font-weight: 400; color:#888; font-size: 9px; margin-top: 2px; }}
  th.st {{ background:#fafafa; white-space: nowrap; }}
  td.act {{ max-width: 340px; color:#333; }}
  td.open, td.skip {{ text-align: center; min-width: 30px; font-variant-numeric: tabular-nums; }}
  td.open {{ outline: 2px solid #1a4b8c; outline-offset: -2px; font-weight: 700; }}
  td.skip {{ color: #999; }}
  .legend span {{ display:inline-block; padding:2px 8px; margin-right:8px; font-size:12px; }}
</style></head><body>
<h1>メイン分析 ① スコアリング結果</h1>
<div class="sub">{len(steps)} step × {len(P)} プローブ ／ open {n_open} セル（太枠）／
閾値 {thr} 以上 ／ セルにカーソルを合わせると起点ごとの内訳が出る</div>
<div class="legend">
  <span style="outline:2px solid #1a4b8c">open：質問生成の対象</span>
  <span style="color:#999">skip：このサイクルでは問わない</span>
</div><br>
<table><tr><th>step</th><th>工程（AO-OP）</th>{head}</tr>
{"".join(rows)}
</table></body></html>
"""


# ==================================================================
# 3. 対話記録
# ==================================================================

def dialogue_md(turns, probes_cfg, rubric_cfg, actions):
    """メイン分析②の対話を全ターン記録する。"""
    P = probes_cfg["probes"]
    kinds = {"system": "質問", "operator": "作業者の自発的補足", "closing": "終盤の開放質問"}
    n_sys = sum(1 for t in turns if t["kind"] == "system")

    out = ["# メイン分析 ② 対話記録\n",
           f"- 全 {len(turns)} ターン（質問 {n_sys} ／ 自発的補足 "
           f"{sum(1 for t in turns if t['kind'] == 'operator')} ／ 終盤 "
           f"{sum(1 for t in turns if t['kind'] == 'closing')}）",
           "- `evidence_id` は EKE-OP の各知識項目の出所ポインタと対応する\n"]

    for t in turns:
        pname = P[t["probe"]]["name_ja"] if t["probe"] in P else "—"
        where = f"step {t['step']}" if t["step"] else "工程指定なし"
        out.append(f"---\n\n### {t['n']}. {kinds.get(t['kind'], t['kind'])}　"
                   f"{where} × {pname}\n")
        if t["step"] in actions:
            out.append(f"工程: {actions[t['step']]}\n")
        if t["question"]:
            out.append(f"**Q:** {t['question']}\n")
        out.append(f"**A:** {t['answer']}\n")
        v = t["verdict"]
        if v:
            axes = "　".join(f"{rubric_cfg['axes'][k]['name_ja']} {'○' if v.get(k) else '×'}"
                            for k in rubric_cfg["axes"])
            if v.get("terminal"):
                res = f"終止状態【{rubric_cfg['terminal_states'].get(v['terminal'], {}).get('name_ja', v['terminal'])}】"
            else:
                res = "充分" if v.get("sufficient") else "不十分 → 追問"
            out.append(f"> 判定: {axes}　⇒ **{res}**  ")
            if v.get("reason"):
                out.append(f"> {v['reason']}  ")
        out.append(f"\n`evidence_id: {t['evidence_id']}`\n")

    return "\n".join(out) + "\n"


# ==================================================================
# 補助
# ==================================================================

def _step_key(s):
    try:
        return [int(x) for x in str(s).split(".")]
    except ValueError:
        return [999]


def _short(text, n=28):
    return text if len(text) <= n else text[:n] + "…"


def _fmt(v):
    return "" if not v else f"{v:g}"


def _color(score, top):
    """0 = 白、最大 = 濃い青。"""
    t = min(max(score / top, 0), 1)
    light = int(98 - 48 * t)
    return f"hsl(212, 60%, {light}%)"
