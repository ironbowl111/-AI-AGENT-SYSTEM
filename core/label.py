"""
core/label.py  —— 処理順序④ step ごとの観点ラベル付け

研究計画 第 4 節に対応。

やること:
  各 step について、8 観点それぞれに 0〜2 の重要度を付ける。
  スコアには必ず reason を添える。理由は次サイクルの入力であり、
  スコアを検証できる唯一の materials でもある。

入力に含めないもの:
  AO-OP の on_failure / completion_criterion などのフィールドは
  **渡さない**。それらは scoring.py の「記述密度」が別途見る。
  両方に見せると同じ根拠を二重に数えることになる。
  → LLM は意味を判定し、規則は字面を判定する、という分担。
"""

import json

from storage import store


def run_labeling(llm, aoop, alignment, sop, previous=None):
    """全 step にラベルを付けて返す。

    返り値: {step_id: {"labels": {probe: 0-2}, "reason": {probe: str}}}
    """
    # ── 【プロンプト】prompts/label.txt ──
    template = store.load_prompt("label")
    probes_cfg = store.load_config("probes")["probes"]
    probes_text = _probes_for_prompt(probes_cfg)

    from core import align as align_mod

    out = {}
    for step in aoop.get("steps", []):
        sid = step["step_id"]

        sop_ref = align_mod.sop_ref_of(alignment, sid)
        sop_text = align_mod.sop_text_of(sop, sop_ref) if sop_ref else "（対応なし）"

        prev_text = "（前サイクルなし）"
        if previous and sid in previous:
            prev_text = json.dumps(previous[sid], ensure_ascii=False, indent=2)

        user = template.format(
            probes=probes_text,
            step=f'{sid}: {step["action"]}',          # ← action のみ。他フィールドは渡さない
            sop_text=sop_text,
            previous=prev_text,
        )

        # ── 【モデル呼び出し】 ──
        res = llm.chat_json(
            "あなたは認知タスク分析の分析者です。",
            user,
            fallback={"labels": {p: 0 for p in probes_cfg}, "reason": {}},
        )

        # 欠けた観点を 0 で埋める（モデルが一部を落とすことがあるため）
        labels = {p: int(res.get("labels", {}).get(p, 0)) for p in probes_cfg}

        # 案A の配分規則に違反していないかを記録する。値は書き換えない。
        # プロンプトで「2 は最大 2 観点、1 は最大 3 観点」と指示しているが、
        # LLM が守る保証はない。守られなかった事実を残さないと、
        # ラベルが定数化しても原因がプロンプトなのかモデルなのか切り分けられない。
        n2 = sum(1 for v in labels.values() if v == 2)
        n1 = sum(1 for v in labels.values() if v == 1)
        viol = []
        if n2 > 2:
            viol.append(f"2 が {n2} 観点（上限 2）")
        if n1 > 3:
            viol.append(f"1 が {n1} 観点（上限 3）")
        if viol:
            print(f"    [配分違反] {sid}: {' / '.join(viol)}")

        out[sid] = {
            "labels": labels,
            "reason": res.get("reason", {}),
            "quota": {"n2": n2, "n1": n1, "violation": viol or None},
        }

    _report_label_spread(out, probes_cfg)
    return out


def _report_label_spread(out, probes_cfg):
    """観点ごとに同じ値が何工程で使われたかを表示する。

    原先生の自己チェック項目「どの観点も同じ値が 35 工程中 25 を超えない」を
    実行時にその場で確認できるようにするためのもの。
    for_nssol では判断基準が 31/35 で 2、感覚が 33/35 で 1 だった。
    """
    from collections import Counter
    total = len(out)
    if not total:
        return
    n_viol = sum(1 for v in out.values() if v.get("quota", {}).get("violation"))
    print(f"    ラベル分布（{total} 工程／配分違反 {n_viol} 工程）")
    for p in probes_cfg:
        c = Counter(v["labels"][p] for v in out.values())
        top_val, top_n = c.most_common(1)[0]
        flag = "  ← 25 超" if top_n > 25 else ""
        dist = "/".join(str(c.get(i, 0)) for i in (0, 1, 2))
        print(f"      {p:22s} 0/1/2 = {dist:10s} 最頻 {top_val}（{top_n}工程）{flag}")


def _probes_for_prompt(probes_cfg):
    """観点の定義をプロンプト用のテキストにする。

    direction をそのまま渡すことで、LLM が観点の意味を勝手に解釈して
    サイクルごとにぶれるのを防ぐ。
    """
    return "\n".join(
        f'- {key}（{v["name_ja"]}）: {v["direction"]}'
        for key, v in probes_cfg.items()
    )