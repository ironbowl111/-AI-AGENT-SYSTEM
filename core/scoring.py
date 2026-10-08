"""
core/scoring.py  —— メイン分析 ① スコアリング

★ このファイルはモデルを一切呼びません。すべて規則計算です。
   同じ入力なら必ず同じ出力になります。だから「なぜこのセルを選んだか」を
   後から説明できます。

ここは研究上いちばん重要な地点です:
   事前分析で決めた「スコープ共通のコンフィグ」と、
   当該ケースの「タスク固有の SOP・AO-OP」が、初めて統合される場所。

1 セル（step × プローブ）のスコアは五つの起点の和（config/scoring.yaml と対応）:

   起点0  事前分析の優先度   probes.yaml の probe_prior    ← 9/2 インタビュー由来
   起点1  LLM の観点ラベル   メイン分析④で LLM が付けた 0〜2
   起点2  SOP 記述の根拠     対応する SOP 項目があれば加点   ← 9/2 インタビュー由来
   起点3  SOP 差分           relation に応じて加点
   起点4  記述密度           AO-OP のフィールドが空なら加点

各起点の寄与は breakdown として個別に残す。合計値だけでは
「どの起点がこのセルを押し上げたか」が後から分からなくなるため。
"""

from core import align as align_mod
from core.eventlog import make_event

SOURCES = ["prior", "label", "sop_rationale", "relation", "density"]
SOURCE_NAMES = {
    "prior": "事前分析の優先度",
    "label": "LLMラベル",
    "sop_rationale": "SOP記述の根拠",
    "relation": "SOP差分",
    "density": "記述密度",
}


# ------------------------------------------------------------------
# 起点0：事前分析の優先度
# ------------------------------------------------------------------

def probe_priors(probes_cfg):
    """probes.yaml の件数から優先度（0〜2）を計算する。

    ★ ここがインタビュー結果がコードに入る地点です。
       件数は 9/2 のアノテーション。basis で数え方を切り替えられる。
    """
    pp = probes_cfg.get("probe_prior")
    if not pp:
        return {p: 0.0 for p in probes_cfg["probes"]}
    counts = pp["counts"][pp.get("basis", "all_mentions")]
    top = max(counts.values()) or 1
    return {p: round(2 * counts.get(p, 0) / top, 1) for p in probes_cfg["probes"]}


# ------------------------------------------------------------------
# 起点4 の前処理：識別力のないフィールドを除外
# ------------------------------------------------------------------

def active_density_fields(aoop, scoring_cfg, verbose=True):
    """記述密度として使えるフィールドだけを選ぶ。

    充足率が 0% や 100% に近いフィールドは、全 step に同じ加点をするだけで
    step 間の区別を生まない。それどころか、その観点だけを一律に押し上げて
    観点間の偏りを作る。
    """
    lo, hi = scoring_cfg.get("density_fill_rate_range", [0.0, 1.0])
    steps = aoop.get("steps", [])
    total = max(len(steps), 1)

    active, report = {}, []
    for field, probe in scoring_cfg["field_to_probe"].items():
        rate = sum(1 for s in steps if s.get(field)) / total
        ok = lo <= rate <= hi
        report.append({"field": field, "probe": probe, "fill_rate": round(rate, 2), "active": ok})
        if ok:
            active[field] = probe
        elif verbose:
            print(f"    密度シグナル無効: {field} 充足率 {rate:.0%}"
                  f"（{lo:.0%}〜{hi:.0%} の範囲外。全 step 一律のため識別力なし）")
    return active, report


# ------------------------------------------------------------------
# スコア行列の計算（全セル。閾値未満も含めて残す）
# ------------------------------------------------------------------

def score_matrix(aoop, alignment, labels, scoring_cfg, probes_cfg, verbose=True):
    """全 step × 全プローブのスコアと、その内訳を計算する。

    返り値:
      {
        "cells":   [{step, probe, score, status, breakdown{起点:値}, reasons[...]}, ...],
        "priors":  {probe: 優先度},
        "density": [{field, fill_rate, active}, ...],
        "threshold": min_cell_score,
      }

    status:
      open  スコア ≥ 閾値。質問生成の対象になる
      skip  スコア < 閾値。このサイクルでは問わない
    """
    w = scoring_cfg["weights"]
    thr = scoring_cfg.get("min_cell_score", 1)
    probe_keys = list(probes_cfg["probes"].keys())
    priors = probe_priors(probes_cfg)
    density_fields, density_report = active_density_fields(aoop, scoring_cfg, verbose)

    cells = []
    for step in aoop.get("steps", []):
        sid = step["step_id"]
        step_labels = labels.get(sid, {}).get("labels", {})
        step_reason = labels.get(sid, {}).get("reason", {})
        rel = align_mod.relation_of(alignment, sid)
        # ao_only（AO-OP にあり SOP にない工程）では SOP 根拠を加点しない。
        # 対応付けの結果に sop_ref が残っていても、「SOP に記述がない動作」である以上
        # 「手順書はなぜこれを求めるのか」は問えないため。
        has_sop = bool(align_mod.sop_ref_of(alignment, sid)) and rel != "ao_only"

        for p in probe_keys:
            b = {s: 0.0 for s in SOURCES}
            why = []

            # 起点0 事前分析の優先度（9/2 インタビュー由来。全 step 共通）
            b["prior"] = priors[p] * w.get("prior", 0)
            if b["prior"]:
                why.append(f"事前分析: 9/2 で該当 {_count(probes_cfg, p)} 件")

            # 起点1 LLM の観点ラベル（メイン分析④）
            v = int(step_labels.get(p, 0))
            b["label"] = v * w["label"]
            if v:
                why.append(f"LLMラベル{v}: {step_reason.get(p, '')}")

            # 起点2 SOP 記述の根拠（9/2 インタビュー由来）
            if has_sop and p in scoring_cfg.get("sop_rationale_probes", []):
                b["sop_rationale"] = w["sop_rationale"]
                why.append("SOP に対応記述あり")

            # 起点3 SOP 差分
            if p in scoring_cfg["relation_to_probes"].get(rel, []):
                b["relation"] = w["relation"]
                why.append(f"SOP差分: {rel}")

            # 起点4 記述密度
            for field, fp in density_fields.items():
                if fp == p and not step.get(field):
                    b["density"] += w["density"]
                    why.append(f"{field} が未記入")

            total = round(sum(b.values()), 1)
            cells.append({
                "step": sid,
                "action": step["action"],
                "probe": p,
                "score": total,
                "status": "open" if total >= thr else "skip",
                "breakdown": {k: round(v, 1) for k, v in b.items()},
                "reasons": why,
            })

    return {"cells": cells, "priors": priors, "density": density_report, "threshold": thr}


def build_cells(cycle, matrix):
    """スコア行列のうち open のセルだけを cell/init イベントにする。"""
    return [
        make_event(cycle, "cell/init",
                   step=c["step"], probe=c["probe"], score=c["score"],
                   breakdown=c["breakdown"], reason="；".join(c["reasons"]))
        for c in matrix["cells"] if c["status"] == "open"
    ]


def _count(probes_cfg, probe):
    pp = probes_cfg.get("probe_prior", {})
    return pp.get("counts", {}).get(pp.get("basis", "all_mentions"), {}).get(probe, 0)


# ------------------------------------------------------------------
# 次に問うセルの選択（メイン分析 ② で使う）
# ------------------------------------------------------------------

def pick_cell(cells, probes_cfg, max_ask, step_order=None, follow_step_order=True,
              max_ask_per_step=None):
    """次に問うセルを選ぶ。無ければ None（＝終止条件の一つ）。

    follow_step_order=True（既定）:
        作業の時間順に step を進み、その step の中でスコア最大のセルを選ぶ。
        映像を見ながらの振り返りでは、行ったり来たりすると作業者が混乱するため。
    follow_step_order=False:
        step をまたいでスコア最大を選ぶ。

    同点は probes.yaml の tie_break_order で決める。ランダムにしない。

    追問の扱い（9/2 の知見：良い知識は 3〜6 ターンの追問連鎖の末尾に出る）:
      - 問い始めて「不十分」だったセルは、新しいセルより先に追問する
      - max_ask_per_step は「その step で新しく開くセルの数」だけを制限する。
        追問は数えない。数えると連鎖が途中で切れる
    """
    probe_rank = {p: i for i, p in enumerate(
        probes_cfg.get("tie_break_order", list(probes_cfg["probes"].keys())))}
    step_rank = {s: i for i, s in enumerate(step_order or [])}

    started = {}                      # step ごとの「問い始めたセル」の数
    for (sid, _), c in cells.items():
        if c["asks"]:
            started[sid] = started.get(sid, 0) + 1

    def eligible(key, c):
        if c["closed"] or c["asks"] >= max_ask:
            return False
        if c["asks"]:                 # 追問は step 上限の対象外
            return True
        return max_ask_per_step is None or started.get(key[0], 0) < max_ask_per_step

    alive = [(k, c) for k, c in cells.items() if eligible(k, c)]
    if not alive:
        return None

    in_progress = lambda c: 0 if c["asks"] else 1       # 追問中のセルを最優先
    if follow_step_order:
        alive.sort(key=lambda kv: (in_progress(kv[1]), step_rank.get(kv[0][0], 999),
                                   -kv[1]["score"], probe_rank.get(kv[0][1], 99)))
    else:
        alive.sort(key=lambda kv: (in_progress(kv[1]), -kv[1]["score"],
                                   probe_rank.get(kv[0][1], 99), step_rank.get(kv[0][0], 999)))
    return alive[0][0]