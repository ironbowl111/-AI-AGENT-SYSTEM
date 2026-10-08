"""
core/extract.py  —— 処理順序⑨ 知識抽出と EKE-OP の生成

研究計画 第 9 節に対応。

重要な点二つ:

  1. AO-OP は書き換えない。入力は読み取り専用で、EKE-OP は別物として作る。
     こうしないと「この知識はどの step のどの対話から来たか」を辿れなくなる。

  2. 8 観点に収まらない知識は unclassified に入れる。捨てない。
     9/2 のデータでは 15 件・9 類型が該当した。固定スキーマに押し込むと
     知識自体は残るが「それが何の類型の知識か」という情報が消える。
"""

import json

from core.eventlog import qa_pairs, coverage, dialogue_turns
from storage import store


def build_ekeop(llm, aoop, events, probes_cfg, settings):
    """イベントログから EKE-OP を組み立てる。

    返り値の構造:
      document        AO-OP から引き継ぐ書誌情報
      steps           step ごとの知識項目（観点別）
      unclassified    8 観点に収まらなかった知識
      coverage        カバレッジ行列（どこを問い、どこを問わなかったか）
      dialogue        対話の全ターン（質問・回答・判定）。知識項目の evidence_id の参照先
    """
    pairs = qa_pairs(events)
    if not pairs:
        return _empty(aoop)

    # ── 【プロンプト】prompts/extract.txt ──
    template = store.load_prompt("extract")
    probes_text = "\n".join(
        f'- {k}（{v["name_ja"]}）: {v["asks"]}'
        for k, v in probes_cfg["probes"].items()
    )
    qa_block = "\n\n".join(
        f'[{p["evidence_id"]}] step={p["step_id"]} probe={p["probe"]} '
        f'initiated_by={p["initiated_by"]}\n'
        f'Q: {p["question"]}\nA: {p["answer"]}'
        for p in pairs
    )

    # ── 【モデル呼び出し】知識抽出 ──
    res = llm.chat_json(
        "あなたは作業手順書の編集者です。",
        template.format(probes=probes_text, qa_block=qa_block),
        max_tokens=3000,
        fallback={"items": []},
    )

    return _assemble(aoop, res.get("items", []), pairs, events, settings)


# ------------------------------------------------------------------

def _assemble(aoop, items, pairs, events, settings):
    """抽出された項目を step ごとに束ね、出所情報を付けて EKE-OP にする。"""
    unclassified_key = settings["output"]["unclassified_key"]
    by_evidence = {p["evidence_id"]: p for p in pairs}

    steps = {}
    for s in aoop.get("steps", []):
        steps[s["step_id"]] = {
            "step_id": s["step_id"],
            "action": s["action"],
            "knowledge": [],
        }

    unclassified = []
    for it in items:
        src = by_evidence.get(it.get("evidence_id"), {})
        entry = {
            "kind": it.get("kind"),
            "text": it.get("text", ""),
            "note": it.get("note", ""),
            # ── 出所ポインタ。幻覚率の計算と信頼度の層別はこれで行う ──
            "evidence_id": it.get("evidence_id"),
            "formulated_by": "operator" if src.get("initiated_by") != "closing" else "closing",
            "initiated_by": src.get("initiated_by", "unknown"),
            "traceable": it.get("evidence_id") in by_evidence,   # False なら幻覚の疑い
        }
        sid = it.get("step_id")
        if entry["kind"] == "unclassified" or sid not in steps:
            entry["step_id"] = sid
            unclassified.append(entry)
        else:
            steps[sid]["knowledge"].append(entry)

    doc = dict(aoop.get("document", {}))
    doc["derived_from"] = doc.get("id")
    doc["id"] = (doc.get("id", "AOOP") or "AOOP").replace("AOOP", "EKEOP")

    return {
        "document": doc,
        "steps": list(steps.values()),
        unclassified_key: unclassified,
        "coverage": coverage(events),
        "dialogue": dialogue_turns(events),
        "stats": {
            "questions_asked": sum(1 for e in events if e.get("kind") == "question/asked"
                                   and e.get("step")),
            "knowledge_items": sum(len(s["knowledge"]) for s in steps.values()),
            "unclassified_items": len(unclassified),
            "untraceable_items": sum(
                1 for s in steps.values() for k in s["knowledge"] if not k["traceable"]
            ) + sum(1 for k in unclassified if not k["traceable"]),
        },
    }


def _empty(aoop):
    """対話が一件も無かった場合の空の EKE-OP。"""
    return {
        "document": aoop.get("document", {}),
        "steps": [],
        "unclassified": [],
        "coverage": {},
        "dialogue": [],
        "stats": {"questions_asked": 0, "knowledge_items": 0, "unclassified_items": 0, "untraceable_items": 0},
    }
