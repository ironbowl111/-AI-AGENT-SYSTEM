"""
core/align.py  —— 処理順序③ SOP と AO-OP の対応付け

研究計画 第 3 節に対応。

やること:
  SOP 項目 ↔ AO-OP step の対応表を作り、五つの関係のいずれかを付ける。
  対応しなかった SOP 項目は unmatched_sop_items に置く。これは
  どの step にも紐づかないので、step を巡回するだけでは永遠に現れない。

サイクル間の継承:
  前サイクルの対応のうち confidence が高いものは再判定せず流用する。
  これが「繰り返しで判定が収束する」仕組みの実体。
"""

import json

from storage import store


def run_alignment(llm, sop, aoop, previous=None, settings=None):
    """SOP と AO-OP の対応表を作る。

    引数:
        llm       core.llm.LLM
        sop       data/sop.json の中身
        aoop      data/aoop.json の中身
        previous  前サイクルの alignment（あれば流用の材料になる）
        settings  config/settings.yaml
    返り値:
        {"pairs": [...], "unmatched_sop_items": [...]}
    """
    # ── 【プロンプト】prompts/align.txt を編集すれば挙動が変わる ──
    template = store.load_prompt("align")

    prev_text = "（前サイクルなし）"
    if previous:
        thr = (settings or {}).get("inheritance", {}).get("alignment_confidence_reuse", 0.8)
        kept = [p for p in previous.get("pairs", []) if p.get("confidence", 0) >= thr]
        prev_text = (f"confidence {thr} 以上の対応（流用してよい）:\n"
                     + json.dumps(kept, ensure_ascii=False, indent=2))

    user = template.format(
        sop=_brief_sop(sop),
        aoop=_brief_aoop(aoop),
        previous=prev_text,
    )

    # ── 【モデル呼び出し】 ──
    result = llm.chat_json(
        "あなたは作業手順書の分析者です。",
        user,
        max_tokens=6000,      # SOP 20 項目 × 理由文で 2000 を超え、JSON が途中で切れるため
        fallback={"pairs": [], "unmatched_sop_items": []},
    )
    result.setdefault("pairs", [])
    result.setdefault("unmatched_sop_items", [])
    return result


def relation_of(alignment, step_id):
    """ある step の関係種別を返す。対応が無ければ None。"""
    for p in alignment.get("pairs", []):
        if step_id in p.get("step_ids", []):
            return p.get("relation")
    return None


def sop_ref_of(alignment, step_id):
    """ある step に対応する SOP 項目 ID を返す。無ければ None。"""
    for p in alignment.get("pairs", []):
        if step_id in p.get("step_ids", []):
            return p.get("sop_ref")
    return None


def sop_text_of(sop, sop_ref):
    """SOP 項目 ID から本文を引く。質問生成のときに文脈として渡す。"""
    for item in sop.get("items", []):
        if item.get("id") == sop_ref:
            return item.get("text", "")
    return "（対応する SOP 記述なし）"


# ------------------------------------------------------------------
# プロンプトに載せる分だけ抜き出す（丸ごと渡すと長すぎて精度が落ちる）
# ------------------------------------------------------------------

def _brief_sop(sop):
    return "\n".join(f'{i["id"]}: {i["text"]}' for i in sop.get("items", []))


def _brief_aoop(aoop):
    return "\n".join(f'{s["step_id"]}: {s["action"]}' for s in aoop.get("steps", []))
