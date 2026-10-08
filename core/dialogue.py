"""
core/dialogue.py  —— 処理順序⑥ 質問・追問・自由発話

研究計画 第 6 節に対応。

三つの経路:
  1. セル駆動の質問   スコア最大のセルから作る。予算を消費する
  2. 追問             深さ不足なら同じセルをもう一度。予算を消費する
  3. 作業者の自発発話 いつでも割り込める。予算を消費しない
                      9/2 では知識の 22/58 件（38%）がこの経路だった

終止状態:
  「理由なし」「不記憶」「事後の自己修正」は浅い回答ではなく到達点。
  追問しても空転するので、セルを閉じて状態を記録する。
"""

from core.eventlog import make_event, last_answer, project_cells
from core.scoring import pick_cell
from storage import store


# ==================================================================
# 回答者（--mode real / sim で切り替わる）
# ==================================================================

class HumanAnswerer:
    """実際の作業者が端末で答える。研究計画の「人の介入その1」。"""

    def __init__(self, free_cfg):
        self.free_cfg = free_cfg
        print("\n" + "=" * 60)
        print(free_cfg["opening"])
        print("=" * 60)

    def answer(self, question):
        """入力を待つ。質問文の表示は run_dialogue 側で行う。"""
        return input("  A> ").strip()

    def free_input(self, hint=None):
        """自発的発話の受け口。空欄なら None を返して先へ進む。

        ★ ここを消すと 9/2 で最も知識を生んだ経路が消えます。
        """
        if hint:
            print(f"\n  {hint}")
        print(f"  {self.free_cfg['marker']}")
        text = input("  +> ").strip()
        return text or None


class SimulatedAnswerer:
    """LLM に作業者を演じさせる。実験前の疎通確認と回帰テスト用。

    本番のデータとしては使えません（作業者本人の知識ではないため）。
    """

    SYSTEM = (
        "あなたはノートPC分解作業の経験者です。インタビューに答えています。"
        "人が話せる分量（150〜250字）で、自分の言葉で答えてください。"
        "理由が思いつかないときは『特に理由はないです』、"
        "思い出せないときは『あまり覚えていないですね』と答えて構いません。"
        "知ったかぶりをしないでください。"
    )

    def __init__(self, llm):
        self.llm = llm

    def answer(self, question):
        # ── 【モデル呼び出し】作業者役 ──
        return self.llm.chat(self.SYSTEM, question, max_tokens=400)

    def free_input(self, hint=None):
        """模擬モードでは自発発話を作らない（人でないと意味がないため）。"""
        return None


def make_answerer(mode, llm, free_cfg):
    """mode に応じた回答者を返す。"""
    return HumanAnswerer(free_cfg) if mode == "real" else SimulatedAnswerer(llm)


# ==================================================================
# 質問生成と深さ判定
# ==================================================================

def generate_question(llm, step_action, probe_key, probes_cfg, previous_answer=None):
    """1 つのセルから質問文を作る。LLM がするのは言い回しだけ。"""
    # ── 【プロンプト】prompts/question.txt ──
    template = store.load_prompt("question")
    p = probes_cfg["probes"][probe_key]

    user = template.format(
        action=step_action,
        direction=p["direction"],                               # 【出典：CTA一般】
        probe_name=p["name_ja"],
        example=p.get("interview_example", "（なし）"),          # 【出典：事前分析＝9/2】
        previous_answer=previous_answer or "（なし。最初の質問です）",
    )
    # ── 【モデル呼び出し】質問生成 ──
    return llm.chat("あなたは認知タスク分析の熟練インタビュアーです。", user, max_tokens=300)


def judge_depth(llm, question, answer, rubric_cfg):
    """回答の深さを 3 軸で判定する。config/rubric.yaml と 1 対 1 で対応。"""
    # ── 【プロンプト】prompts/judge.txt ──
    template = store.load_prompt("judge")

    axes_text = "\n".join(
        f'- {k}（{v["name_ja"]}）: {v["question"]}'
        for k, v in rubric_cfg["axes"].items()
    )
    terminal_text = "\n".join(
        f'- {k}（{v["name_ja"]}）: {v["detect"]}'
        for k, v in rubric_cfg["terminal_states"].items()
    )

    user = template.format(
        axes=axes_text,
        terminal=terminal_text,
        threshold=rubric_cfg["sufficient_threshold"],
        question=question,
        answer=answer,
    )
    # ── 【モデル呼び出し】深さ判定 ──
    return llm.chat_json(
        "あなたは回答の深さを判定する評価者です。",
        user,
        fallback={"sufficient": False, "terminal": None, "reason": "判定失敗"},
    )


# ==================================================================
# 対話ループ本体
# ==================================================================

def run_dialogue(llm, run, cycle, aoop, answerer, cfg):
    """1 サイクル分の対話を回す。イベントを追記しながら進む。

    cfg には probes / rubric / settings / scoring を入れて渡す。
    """
    dlg = cfg["settings"]["dialogue"]
    budget = dlg["budget"]
    max_ask = dlg["max_ask_per_cell"]

    steps = {s["step_id"]: s for s in aoop.get("steps", [])}
    step_order = [s["step_id"] for s in aoop.get("steps", [])]   # 作業の時間順
    follow_order = dlg.get("follow_step_order", True)
    max_per_step = dlg.get("max_ask_per_step")
    last_step = None
    asked = 0

    while asked < budget:
        events = store.read_events(run, cycle)
        cells = project_cells(events)

        key = pick_cell(cells, cfg["probes"], max_ask, step_order, follow_order,
                        max_per_step)
        if key is None:
            break                       # 終止条件その1：開いたセルを問い切った
        step_id, probe = key

        # step が切り替わったら自発発話を促す
        if step_id != last_step:
            _collect_free_input(answerer, run, cycle, step_id,
                                dlg["free_input"]["on_step_change"])
            last_step = step_id

        prev = last_answer(events, step_id, probe)
        q = generate_question(llm, steps[step_id]["action"], probe, cfg["probes"], prev)
        qev = make_event(cycle, "question/asked", step=step_id, probe=probe, text=q)
        store.append_event(run, cycle, qev)

        asked += 1
        cell_score = cells[key]["score"]
        pname = cfg["probes"]["probes"][probe]["name_ja"]
        _show_question(asked, budget, step_id, steps[step_id]["action"],
                       probe, pname, cell_score, prev is not None, q)

        a = answerer.answer(q)
        if not isinstance(answerer, HumanAnswerer):
            _show_text("A", a)
        aev = make_event(cycle, "answer/received", step=step_id, probe=probe,
                         text=a, reply_to=qev["id"], initiated_by="system")
        store.append_event(run, cycle, aev)

        v = judge_depth(llm, q, a, cfg["rubric"])
        store.append_event(run, cycle,
                           make_event(cycle, "judge/verdict", answer=aev["id"], **v))

        if v.get("sufficient"):
            store.append_event(run, cycle,
                               make_event(cycle, "cell/closed", step=step_id, probe=probe,
                                          evidence=aev["id"], terminal=v.get("terminal")))

        can_follow = cells[key]["asks"] + 1 < max_ask     # 今回の質問を含めた回数
        _show_verdict(v, cfg["rubric"], can_follow)

        # 各回答のあとに自発発話の受け口を置く（予算を消費しない）
        _collect_free_input(answerer, run, cycle, step_id)

    _closing_questions(answerer, run, cycle, dlg["closing_questions"])
    store.append_event(run, cycle, make_event(cycle, "turn/end", asked=asked))
    return asked


def _collect_free_input(answerer, run, cycle, step_id, hint=None):
    """自発発話を拾ってログに入れる。probe は付けない（事後に分類する）。"""
    text = answerer.free_input(hint)
    if not text:
        return
    print(f"  ＋ 自発的補足を記録しました（予算外）")
    store.append_event(run, cycle, make_event(
        cycle, "answer/received",
        step=step_id, probe=None, text=text,
        reply_to=None, initiated_by="operator",   # ← 予算外・事後分類の目印
    ))


def _closing_questions(answerer, run, cycle, questions):
    """終盤に置く開放質問。9/2 ではこの 1 問が枠外知識 3 件を生んだ。"""
    print(f"\n{'─'*60}\n  終盤の開放質問（予算外）\n{'─'*60}")
    for q in questions:
        qev = make_event(cycle, "question/asked", step=None, probe=None, text=q)
        store.append_event(run, cycle, qev)
        _show_text("Q", q)
        a = answerer.answer(q)
        if not isinstance(answerer, HumanAnswerer):
            _show_text("A", a)
        if not a:
            continue
        store.append_event(run, cycle, make_event(
            cycle, "answer/received", step=None, probe=None,
            text=a, reply_to=qev["id"], initiated_by="closing",
        ))


# ==================================================================
# 端末表示（対話の中身をその場で見えるようにする）
# ==================================================================

def _show_question(n, budget, step_id, action, probe, pname, score, is_followup, q):
    """1 ターン分の見出しと質問文を表示する。"""
    kind = "追問" if is_followup else "質問"
    print(f"\n{'─'*60}")
    print(f"  [{n:2d}/{budget}] {kind}  step {step_id}  ×  {pname}（{probe}）  score={score}")
    print(f"  工程: {action}")
    print(f"{'─'*60}")
    _show_text("Q", q)


def _show_text(tag, text):
    """Q: / A: の本文を字下げして表示する。"""
    lines = (text or "（空欄）").splitlines() or [""]
    print(f"  {tag}: {lines[0]}")
    for ln in lines[1:]:
        print(f"     {ln}")


def _show_verdict(v, rubric_cfg, can_follow=True):
    """深さ判定の 3 軸と結論を 1 行で表示する。"""
    axes = " ".join(
        f"{rubric_cfg['axes'][k]['name_ja']}{'○' if v.get(k) else '×'}"
        for k in rubric_cfg["axes"]
    )
    if v.get("terminal"):
        name = rubric_cfg["terminal_states"].get(v["terminal"], {}).get("name_ja", v["terminal"])
        result = f"終止状態【{name}】→ セルを閉じる"
    elif v.get("sufficient"):
        result = "充分 → セルを閉じる"
    elif can_follow:
        result = "不十分 → 追問へ"
    else:
        result = "不十分 → 追問上限に達したため次のセルへ（未解決として記録）"
    print(f"  判定: {axes}  ⇒ {result}")
    if v.get("reason"):
        print(f"        理由: {v['reason']}")
