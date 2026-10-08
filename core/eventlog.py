"""
core/eventlog.py

イベントログと、そこからの投影。

設計の要:
  状態を変数として持たず、ログから毎回計算する。
  こうしておくと、任意の時点の状態を復元できる、なぜその質問をしたのか
  説明できる、対話が途中で落ちても再開できる。

  カバレッジ行列は「保存されているデータ」ではなく「ログの投影」です。
"""

import time
import uuid


def make_event(cycle, kind, **data):
    """イベント 1 件を作る。id は後続イベントから参照される出所ポインタになる。"""
    return {
        "id": uuid.uuid4().hex[:8],
        "ts": round(time.time(), 3),
        "cycle": cycle,
        "kind": kind,
        **data,
    }


def project_cells(events):
    """イベント列を畳み込んで、(step_id, probe) ごとの状態を作る。

    返り値: {(step_id, probe): {score, reason, asks, closed, terminal}}

    kind の意味:
      cell/init        セルを開き、スコアと理由を確定した
      question/asked   そのセルで質問した
      cell/closed      充分と判定した、または終止状態に達した
    """
    cells = {}
    for ev in events:
        k = ev.get("kind")

        if k == "cell/init":
            cells[(ev["step"], ev["probe"])] = {
                "score": ev["score"],
                "reason": ev.get("reason", ""),
                "asks": 0,
                "closed": False,
                "terminal": None,
            }

        elif k in ("question/asked", "cell/closed"):
            cell = cells.get((ev.get("step"), ev.get("probe")))
            if cell is None:
                continue          # step/probe を持たないイベント（自由発話など）は飛ばす
            if k == "question/asked":
                cell["asks"] += 1
            else:
                cell["closed"] = True
                cell["terminal"] = ev.get("terminal")

    return cells


def last_answer(events, step, probe):
    """同じセルでの直前の回答を返す。追問のときプロンプトに渡す。"""
    for ev in reversed(events):
        if (ev.get("kind") == "answer/received"
                and ev.get("step") == step and ev.get("probe") == probe):
            return ev["text"]
    return None


def coverage(events):
    """カバレッジ行列を人が読める形にする。論文の図のデータになる。"""
    cells = project_cells(events)
    out = {}
    for (s, p), c in cells.items():
        if c["closed"]:
            state = "closed"
        elif c["asks"]:
            state = "probed"
        else:
            state = "open"
        out[f"{s}|{p}"] = {"state": state, "score": c["score"], "terminal": c["terminal"]}
    return out


def qa_pairs(events):
    """質問と回答の対を時系列で取り出す。知識抽出に渡す。"""
    by_id = {e["id"]: e for e in events}
    pairs = []
    for ev in events:
        if ev.get("kind") != "answer/received":
            continue
        q = by_id.get(ev.get("reply_to"), {})
        pairs.append({
            "step_id": ev.get("step"),
            "probe": ev.get("probe"),
            "question": q.get("text", "（自発的発話のため質問なし）"),
            "answer": ev["text"],
            "evidence_id": ev["id"],
            "initiated_by": ev.get("initiated_by", "system"),
        })
    return pairs


def dialogue_turns(events):
    """対話を 1 ターンずつに組み立てる。質問・回答・判定を一つにまとめる。

    ターンの種類（kind）:
      system     セルから生成した質問への回答（予算を消費）
      operator   作業者の自発的補足（予算外）
      closing    終盤の開放質問への回答（予算外）
    """
    by_id = {e["id"]: e for e in events}
    verdict_of = {e.get("answer"): e for e in events if e.get("kind") == "judge/verdict"}

    turns = []
    for ev in events:
        if ev.get("kind") != "answer/received":
            continue
        q = by_id.get(ev.get("reply_to"), {})
        v = verdict_of.get(ev["id"], {})
        turns.append({
            "n": len(turns) + 1,
            "kind": ev.get("initiated_by", "system"),
            "step": ev.get("step"),
            "probe": ev.get("probe"),
            "question": q.get("text"),
            "answer": ev.get("text"),
            "verdict": {k: v.get(k) for k in
                        ("specificity", "causality", "clarity", "terminal", "sufficient", "reason")}
                       if v else None,
            "evidence_id": ev["id"],
        })
    return turns
