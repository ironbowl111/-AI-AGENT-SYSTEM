"""
Theme B: AI-Driven Expert Dialogue System for Manual Refinement
================================================================
Directory layout:
  theme_b_project/
  ├── env/
  │   └── .env          ← API key + provider settings
  ├── data/
  │   └── *.json        ← JSON files (updated in-place)
  └── theme_b_pipeline.py

Each run:
  1. Reads  data/<input>.json
  2. Detects knowledge gaps
  3. Runs expert dialogue (simulated or real)
  4. Extracts QA knowledge units (BGE embedding + DBSCAN)
  5. Writes knowledge back into the SAME file
  6. Appends a new entry to revision_history with version bump + timestamp

Usage:
  python theme_b_pipeline.py data/my_task.json [--real] [--no-semantic]

  --real        : real expert answers via terminal
  --no-semantic : skip LLM vague-expression detection
"""

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN

# ============================================================
# 0. CONFIG  ← secondary knobs (primary settings are in .env)
# ============================================================
ENV_FILE       = Path(__file__).parent / "env" / "env"
DATA_DIR       = Path(__file__).parent / "data"

MAX_ROUNDS     = 3      # dialogue rounds per run
Q_PER_ROUND    = 3      # max questions per round

EMBED_MODEL    = "BAAI/bge-small-en-v1.5"   # swap to bge-large-en-v1.5 for higher accuracy
DBSCAN_EPS     = 0.30   # cosine-distance threshold (higher = merge more aggressively)
DBSCAN_MIN_PTS = 2      # min points to form a cluster

NEEDS_VERIFY   = "needs_verification"


# ============================================================
# 1. ENV LOADER
# ============================================================
def load_env() -> dict:
    load_dotenv(ENV_FILE)
    cfg = {
        "provider":  os.getenv("PROVIDER",  "openai"),
        "api_key":   os.getenv("API_KEY",   ""),
        "base_url":  os.getenv("BASE_URL",  "https://api.openai.com/v1"),
        "model":     os.getenv("MODEL",     "gpt-4o-mini"),
        "expert_id": os.getenv("EXPERT_ID", "EXP-001"),
    }
    if not cfg["api_key"] or cfg["api_key"].startswith("sk-..."):
        sys.exit(f"[ERROR] Please set API_KEY in {ENV_FILE}")
    return cfg


def make_client(cfg: dict) -> OpenAI:
    """Both OpenAI and Qwen use the OpenAI-compatible SDK."""
    return OpenAI(api_key=cfg["api_key"], base_url=cfg["base_url"])


def chat(client: OpenAI, model: str, system: str, user: str, max_tokens: int = 600) -> str:
    """Unified chat call for OpenAI / Qwen."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    resp = client.chat.completions.create(
        model=model, messages=messages, max_tokens=max_tokens
    )
    return resp.choices[0].message.content.strip()


# ============================================================
# 2. VERSION & REVISION HISTORY HELPERS
# ============================================================
def _bump_version(current: str) -> str:
    """'1.0' → '2.0', '2.3' → '3.3', fallback to '2.0'."""
    try:
        major, minor = current.split(".")
        return f"{int(major)+1}.{minor}"
    except Exception:
        return "2.0"


def _new_session_id() -> str:
    now = datetime.now(timezone.utc)
    seq = str(uuid.uuid4())[:3].upper()
    return f"DLG-{now.strftime('%Y-%m%d')}-{seq}"


def append_revision(schema: dict, cfg: dict, session_id: str) -> dict:
    """
    Bump document.version and append a new entry to revision_history.
    Mirrors the schema structure in 付録B:
      {
        "version": "2.0",
        "timestamp": "2026-01-09T11:45:00Z",
        "method": "expert_dialogue_refinement",
        "expert_id": "EXP-042",
        "session_id": "DLG-2026-0109-001"
      }
    """
    old_version = schema.get("document", {}).get("version", "1.0")
    new_version = _bump_version(old_version)
    now_iso     = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    schema.setdefault("document", {})["version"]              = new_version
    schema["document"]["generation_timestamp"]                 = now_iso
    schema["document"]["generation_method"]                    = "video_analysis + expert_dialogue"

    schema.setdefault("revision_history", []).append({
        "version":    new_version,
        "timestamp":  now_iso,
        "method":     "expert_dialogue_refinement",
        "expert_id":  cfg["expert_id"],
        "session_id": session_id,
    })
    return schema


# ============================================================
# 3. GAP DETECTOR
# ============================================================
class GapDetector:

    def detect_structural(self, schema: dict) -> list[dict]:
        gaps = []

        if not schema.get("techniques"):
            gaps.append({"field": "techniques", "type": "expert_tip", "step_id": None})

        if not schema.get("troubleshooting"):
            gaps.append({"field": "troubleshooting", "type": "exception_handling", "step_id": None})

        ws = schema.get("prerequisites", {}).get("workspace", {})
        if not ws or ws.get("source_status") == NEEDS_VERIFY:
            gaps.append({"field": "prerequisites.workspace", "type": "precondition", "step_id": None})

        for step in schema.get("steps", []):
            sid  = step.get("step_id")
            name = step.get("name", f"step_{sid}")

            if step.get("on_failure") is None:
                gaps.append({
                    "field": f"steps[{sid}].on_failure",
                    "type": "exception_handling",
                    "step_id": sid, "step_name": name,
                })

            verif = step.get("verification", {})
            if verif.get("detail_status") == NEEDS_VERIFY or not verif.get("criterion"):
                gaps.append({
                    "field": f"steps[{sid}].verification.detail",
                    "type": "judgment_criterion",
                    "step_id": sid, "step_name": name,
                })

            for act in step.get("actions", []):
                if act.get("rationale") is None:
                    gaps.append({
                        "field": f"steps[{sid}].actions[{act.get('action_id')}].rationale",
                        "type": "sensory_cue",
                        "step_id": sid, "step_name": name,
                        "action_instruction": act.get("instruction", ""),
                    })
                    break

        return gaps

    def detect_semantic(self, schema: dict, client: OpenAI, model: str) -> list[dict]:
        step_texts = [
            {"step_id": s["step_id"], "step_name": s.get("name",""),
             "instruction": a.get("instruction","")}
            for s in schema.get("steps", [])
            for a in s.get("actions", [])
        ]
        if not step_texts:
            return []

        raw = chat(
            client, model,
            system="",
            user=(
                "以下は作業手順書の動作記述リストです。\n"
                "初心者が実行できないほど曖昧な表現（例：「正常を確認」「適切に締める」）を検出してください。\n"
                "曖昧な動作のみJSON配列で返してください（バッククォートなし）:\n"
                '[{"step_id":1,"step_name":"...","instruction":"...","vague_reason":"..."}]\n\n'
                f"動作リスト:\n{json.dumps(step_texts, ensure_ascii=False)}"
            ),
            max_tokens=600,
        )
        try:
            return [
                {"field": f"steps[{v['step_id']}].semantic_gap",
                 "type": "judgment_criterion",
                 "step_id": v["step_id"], "step_name": v.get("step_name",""),
                 "action_instruction": v["instruction"],
                 "reason": v.get("vague_reason","")}
                for v in json.loads(raw)
            ]
        except (json.JSONDecodeError, KeyError):
            return []

class QuestionGenerator:
    """
    CTA-grounded question generator following CPP (Clark, 2004) and CDM (Klein et al., 1989).

    CPP probes: (a) action sequence, (b) decisions & criteria, (c) concepts/principles,
                (d) initiating conditions, (e) equipment, (f) sensory cues, (g) standards
    CDM probes: (a) perceptual cues, (b) prior knowledge, (c) goals,
                (d) decision alternatives, (e) situation assessment

    Key CTA finding (Clark & Elen, 2006): experts are unaware of ~70% of their
    own decisions — structured probes are required to surface automated knowledge.
    """

    # Each gap type maps to the CTA probe dimension best suited to elicit it,
    # plus a concrete probe direction for the LLM to follow.
    _PROBE_MAP = {
        "judgment_criterion": (
            "知覚的手がかり抽出",
            "専門家が状況を正しく評価するために使う知覚的手がかりを引き出す。"
            "「その動作が正しく完了したことをどうやって判断しますか？何を見て・聞いて・感じて合否を判定していますか？」という方向で問う。",
        ),
        "sensory_cue": (
            "感覚的情報抽出",
            "視覚・聴覚・触覚・嗅覚など、専門家が使う感覚的情報を引き出す。"
            "「その動作をするとき、どんな感覚を頼りにしていますか？初心者には気づきにくい感覚的なサインはありますか？」という方向で問う。",
        ),
        "exception_handling": (
            "例外・意思決定抽出",
            "異常・失敗事例における意思決定と対処の選択肢を引き出す。"
            "「そのステップで問題が起きたとき、最初に何に気づきますか？どんな選択肢を考え、何を根拠に対処法を選びますか？」という方向で問う。",
        ),
        "expert_tip": (
            "暗黙知・技法抽出",
            "専門家が自動化・無意識化している暗黙的な技法や判断根拠を引き出す。"
            "「初心者が見落としがちで、あなたは無意識にやっている工夫や判断はありますか？なぜその方法でやるのですか？」という方向で問う。",
        ),
        "precondition": (
            "前提条件抽出",
            "作業を正しく開始するための条件・環境・前提知識を引き出す。"
            "「この作業を始める前に何を確認しますか？どんな状態になっていれば次に進んでよいですか？」という方向で問う。",
        ),
        "completion_standard": (
            "完了基準抽出",
            "速さ・精度・品質の具体的な合格基準を引き出す。"
            "「完了の判断基準は何ですか？どの程度の精度・速さ・状態であれば合格ですか？数値や具体的な状態で教えてください。」という方向で問う。",
        ),
        "quality_check": (
            "品質確認手順抽出",
            "品質確認の具体的手順と問題のサインを引き出す。"
            "「品質をどうやって確認しますか？何が問題のサインになりますか？見逃しやすい欠陥はどんなものですか？」という方向で問う。",
        ),
        "safety_note": (
            "安全リスク抽出",
            "安全上の禁止事項・リスク・回避行動を引き出す。"
            "「この作業で特に危険な場面はどこですか？どんな間違いが重大な結果を招きますか？」という方向で問う。",
        ),
    }

    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model  = model

    # 4-stage progression labels (付録A 対話設計原則1)
    _STAGE_LABEL = {
        1: ("第1段階：全体像の確認",  "専門家の全体的なアプローチを把握する。「どのようにやりますか？」という方向で問う。"),
        2: ("第2段階：技法の明確化",  "観察された特定の動作・工夫の理由と名前を引き出す。「なぜその動作をしますか？」という方向で問う。"),
        3: ("第3段階：基準の明確化",  "合否・完了・品質の定量的な判断基準を引き出す。「どうやって正しいと判断しますか？」という方向で問う。"),
        4: ("第4段階：例外・バリエーション", "失敗パターン・例外ケース・代替手順を引き出す。「問題が起きたらどうしますか？」という方向で問う。"),
    }

    def generate(self, gaps: list[dict], ctx: str, max_q: int = Q_PER_ROUND, round_num: int = 1) -> list[dict]:
        if not gaps:
            return []

        seen, selected = set(), []
        for gap in gaps:
            if gap["type"] not in seen:
                selected.append(gap)
                seen.add(gap["type"])
            if len(selected) >= max_q:
                break

        stage_key  = min(round_num, 4)
        stage_name, stage_dir = self._STAGE_LABEL[stage_key]

        probe_guide = "\n".join(
            f"ギャップ{i} | 種別: {g['type']} | 手法: {self._PROBE_MAP.get(g['type'], ('general', 'general probe'))[0]}\n"
            f"  → {self._PROBE_MAP.get(g['type'], ('', '具体的な質問を生成する。'))[1]}"
            for i, g in enumerate(selected)
        )
        indexed = [{"idx": i, **g} for i, g in enumerate(selected)]

        raw = chat(
            self.client, self.model,
            system=(
                "あなたはCognitive Task Analysis（CTA）の専門インタビュアーです。\n\n"
                "【理論的背景】\n"
                "Clark & Elen (2006) によれば、専門家は自分の意思決定の約70%を自覚していない。"
                "このため、自由回答では暗黙知の大半が報告されない。"
                "CPP (Clark, 2004) とCDM (Klein et al., 1989) の構造化プローブを使って、"
                "自動化・無意識化された知識を強制的に言語化させる必要がある。\n\n"
                f"【現在のインタビュー段階】\n{stage_name}\n{stage_dir}\n\n"
                "【各ギャップへのプローブ指示】\n"
                f"{probe_guide}\n\n"
                "【質問生成の原則】\n"
                "1. 「なぜ」「どうやって分かる」「何を頼りに」を核心に据える\n"
                "2. 専門家が当たり前すぎて説明しないことを意識的に引き出す\n"
                "3. 抽象的・一般的な質問ではなく、この具体的なステップ・動作に特化させる\n"
                "4. 感覚・知覚・判断基準・代替案・失敗事例を具体的に問う\n"
                "5. 現在の段階に合ったレベルの質問にする（段階に応じて深掘りする）\n\n"
                "各ギャップに対して質問を1つ生成し、JSON配列のみ返してください（バッククォート・前置き文不要）:\n"
                '[{"idx":0,"question":"具体的なCTAプローブ質問"}]'
            ),
            user=(
                f"作業コンテキスト:\n{ctx[:1500]}\n\n"
                f"知識ギャップ詳細:\n{json.dumps(indexed, ensure_ascii=False)}"
            ),
            max_tokens=1000,
        )
        try:
            items = json.loads(raw)
            result = []
            for item in items:
                idx = item.get("idx", 0)
                if idx < len(selected):
                    gap = selected[idx]
                    result.append({
                        "question":  item["question"],
                        "gap_field": gap["field"],
                        "gap_type":  gap["type"],
                        "step_id":   gap.get("step_id"),
                    })
            return result[:max_q]
        except (json.JSONDecodeError, KeyError):
            return []


# ============================================================
# 5. DIALOGUE MANAGER
# ============================================================
class DialogueManager:

    def __init__(self, client: OpenAI, model: str, simulate: bool = True):
        self.client   = client
        self.model    = model
        self.simulate = simulate
        self.log: list[dict] = []

    def run_round(self, questions: list[dict], ctx: str) -> list[dict]:
        round_qa = []
        for q in questions:
            print(f"\n[AI] {q['question']}")
            answer = (
                self._simulate(q["question"], ctx)
                if self.simulate
                else input("[専門家] >>> ").strip()
            )
            print(f"[専門家] {answer}")

            # Follow-up echo: AI rephrases key point for confirmation (付録A 対話設計原則4)
            echo_q = self._echo_question(answer)
            print(f"\n[AI] {echo_q}")
            if self.simulate:
                supplement = self._simulate_confirm(echo_q, answer)
            else:
                supplement = input("[専門家] >>> ").strip()
            print(f"[専門家] {supplement}")

            # Merge original answer + any correction/supplement from confirmation
            merged_answer = answer if supplement in ("その通りです", "はい", "") else f"{answer}\n【補足】{supplement}"
            entry = {**q, "answer": merged_answer}
            round_qa.append(entry)
            self.log.append(entry)
        return round_qa

    def _simulate(self, question: str, ctx: str) -> str:
        return chat(
            self.client, self.model,
            system=(
                "あなたは8年以上の実務経験を持つ熟練作業専門家です。人間がインタビューの中で自然に口頭で答えられるような粒度・深さで200文字程度で回答してください。箇条書きや表などは使わず、直列の文章で回答してください\n"
             
            ),
            user=f"コンテキスト:\n{ctx}\n\n質問:\n{question}",
            max_tokens=500,
        )

    def _echo_question(self, answer: str) -> str:
        return chat(
            self.client, self.model,
            system=(
                "CTAインタビュアーとして、専門家の回答の要点を1文で言い換えた確認質問を作ってください。\n"
                "「つまり〜ということですか？」または「〜という理解で合っていますか？」の形式で返してください。\n"
                "確認質問のみを返してください（前置き・説明不要）。"
            ),
            user=f"専門家の回答: {answer}",
            max_tokens=120,
        )

    def _simulate_confirm(self, echo_q: str, original_answer: str) -> str:
        return chat(
            self.client, self.model,
            system=(
                "あなたは熟練作業専門家です。インタビュアーの確認質問に対して、"
                "前の回答が正しければ「その通りです」と答え、補足が必要なら1〜2文で追加してください。"
            ),
            user=f"確認質問: {echo_q}\n前の回答: {original_answer}",
            max_tokens=150,
        )


# ============================================================
# 6. QA PAIR EXTRACTOR  (AI Knowledge Assist 3-stage)
# ============================================================
class QAPairExtractor:

    def __init__(self, client: OpenAI, model: str):
        self.client = client
        self.model  = model
        print(f"  Loading embedding model: {EMBED_MODEL} ...")
        self.embedder = SentenceTransformer(EMBED_MODEL)
        print("  Embedding model ready.")

    def _clean(self, qa: dict) -> dict | None:
        raw = chat(
            self.client, self.model,
            system=(
                "質問と回答のペアを作業マニュアル用の知識ユニットに整理してください。\n"
                "以下のJSON形式のみで返してください（バッククォート・前置き文不要）:\n"
                '{"knowledge_type":"技法名またはカテゴリ","summary":"1文の要約","detail":"詳細説明",'
                '"condition":"適用条件（なければ空文字）",'
                '"failure_modes":["失敗パターン1（なければ空リスト）"],'
                '"success_indicators":["成功の判断基準1（なければ空リスト）"]}'
            ),
            user=f"Q: {qa['question']}\nA: {qa['answer']}",
            max_tokens=500,
        )
        try:
            unit = json.loads(raw)
            return {**unit, "gap_field": qa["gap_field"],
                    "gap_type": qa["gap_type"], "step_id": qa.get("step_id")}
        except (json.JSONDecodeError, KeyError):
            return None

    def _cluster(self, units: list[dict]) -> dict[str, list[dict]]:
        if len(units) <= 1:
            return {"0": units}

        texts      = [u.get("summary", u.get("detail", "")) for u in units]
        embeddings = self.embedder.encode(texts, normalize_embeddings=True, show_progress_bar=False)

        cos_dist = np.clip(1.0 - (embeddings @ embeddings.T), 0.0, 2.0)

        labels = DBSCAN(eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_PTS,
                        metric="precomputed").fit_predict(cos_dist)

        clusters: dict[str, list[dict]] = {}
        noise_n = 0
        for unit, label in zip(units, labels):
            key = f"noise_{noise_n}" if label == -1 else str(label)
            if label == -1:
                noise_n += 1
            clusters.setdefault(key, []).append(unit)
        return clusters


    def _represent(self, items: list[dict]) -> dict:
        if len(items) == 1:
            return items[0]
        merged = "\n".join(f"- {i['summary']}: {i['detail']}" for i in items)
        raw = chat(
            self.client, self.model,
            system=(
                "複数の類似知識項目を1つの代表項目にまとめてください。\n"
                "以下のJSON形式のみで返してください（バッククォート不要）:\n"
                '{"knowledge_type":"...","summary":"...","detail":"...","condition":""}'
            ),
            user=merged,
            max_tokens=400,
        )
        try:
            m = json.loads(raw)
            return {**m, "gap_field": items[0]["gap_field"],
                    "gap_type": items[0]["gap_type"], "step_id": items[0].get("step_id")}
        except (json.JSONDecodeError, KeyError):
            return items[0]

    def extract(self, raw_qa: list[dict]) -> list[dict]:
        cleaned = [u for qa in raw_qa if (u := self._clean(qa)) is not None]
        if not cleaned:
            return []

        # Cluster within each gap_type separately — prevents merging knowledge
        # of different types (e.g. expert_tip and exception_handling) into one unit.
        by_type: dict[str, list[dict]] = {}
        for u in cleaned:
            by_type.setdefault(u.get("gap_type", "unknown"), []).append(u)

        representatives = []
        for items in by_type.values():
            clusters = self._cluster(items)
            representatives.extend(self._represent(c) for c in clusters.values())
        return representatives


# ============================================================
# 7. MANUAL UPDATER  (writes knowledge units back into schema)
# ============================================================
class ManualUpdater:

    def apply(self, schema: dict, units: list[dict]) -> dict:
        for u in units:
            gtype, sid = u["gap_type"], u.get("step_id")
            detail, name = u.get("detail",""), u.get("knowledge_type","Unknown")

            if gtype == "expert_tip":
                schema.setdefault("techniques", []).append({
                    "id":                f"tech_{len(schema.get('techniques',[]))+1:03d}",
                    "name":              name,
                    "purpose":           u.get("summary", ""),
                    "steps":             [detail],
                    "failure_modes":     u.get("failure_modes", []),
                    "success_indicators": u.get("success_indicators", []),
                    "source":            "expert_dialogue",
                })
                schema["techniques_status"] = "confirmed"
                schema.setdefault("expert_tips", []).append({
                    "tip":    u.get("summary", ""),
                    "detail": detail,
                    "source": "expert_dialogue",
                })
                schema["expert_tips_status"] = "confirmed"

            elif gtype == "exception_handling":
                if sid is None:
                    schema.setdefault("troubleshooting", []).append({
                        "problem":   name,
                        "solution":  detail,
                        "condition": u.get("condition",""),
                        "source":    "expert_dialogue",
                    })
                    schema["troubleshooting_status"] = "confirmed"
                else:
                    for step in schema.get("steps", []):
                        if step["step_id"] == sid:
                            step["on_failure"]        = detail
                            step["on_failure_status"] = "confirmed"
                            break

            elif gtype in ("judgment_criterion", "sensory_cue", "completion_standard"):
                for step in schema.get("steps", []):
                    if step["step_id"] == sid:
                        step.setdefault("verification",{})["detail"]   = detail
                        step["verification"]["detail_status"]           = "confirmed"
                        break

            elif gtype == "precondition":
                schema.setdefault("prerequisites",{}).setdefault("expert_notes",[]).append(detail)

            elif gtype == "safety_note":
                schema.setdefault("safety_notes",[]).append(
                    {"note": detail, "source": "expert_dialogue"}
                )

        schema.setdefault("document",{})["knowledge_units_added"] = (
            schema["document"].get("knowledge_units_added", 0) + len(units)
        )
        return schema


# ============================================================
# 8. PIPELINE ORCHESTRATOR
# ============================================================
def run_pipeline(json_path: str, simulate: bool = True, semantic_check: bool = True) -> None:
    cfg    = load_env()
    client = make_client(cfg)
    model  = cfg["model"]

    target = Path(json_path)
    if not target.exists():
        sys.exit(f"[ERROR] File not found: {target}")

    with open(target, encoding="utf-8") as f:
        schema = json.load(f)

    task_name  = schema.get("document", {}).get("task_name", target.stem)
    session_id = _new_session_id()

    print(f"\n{'='*62}")
    print(f" Theme B Pipeline")
    print(f" Task      : {task_name}")
    print(f" File      : {target}")
    print(f" Session   : {session_id}")
    print(f" Provider  : {cfg['provider']}  model={model}")
    print(f" Mode      : {'LLM-simulated expert' if simulate else 'Real expert'}")
    print(f"{'='*62}")

    detector  = GapDetector()
    qgen      = QuestionGenerator(client, model)
    dialogue  = DialogueManager(client, model, simulate=simulate)
    extractor = QAPairExtractor(client, model)
    updater   = ManualUpdater()

    all_raw_qa: list[dict] = []

    # Build context: video timeline (timestamps) + schema overview (付録A 対話設計原則2)
    timeline_lines = [
        f"[{act.get('start_sec','?')}-{act.get('end_sec','?')}s] "
        f"step{step.get('step_id','?')}: {act.get('instruction','')}"
        for step in schema.get("steps", [])
        for act in step.get("actions", [])
    ]
    timeline_ctx = "【動画タイムライン】\n" + "\n".join(timeline_lines) + "\n\n" if timeline_lines else ""
    ctx = timeline_ctx + json.dumps(schema, ensure_ascii=False)[:1800]

    for rnd in range(1, MAX_ROUNDS + 1):
        print(f"\n{'─'*40}  Round {rnd}/{MAX_ROUNDS}")

        gaps = detector.detect_structural(schema)
        if semantic_check:
            gaps += detector.detect_semantic(schema, client, model)

        if not gaps:
            print("  ✓ No gaps remaining — early stop.")
            break

        print(f"  Gaps detected: {len(gaps)}")
        questions = qgen.generate(gaps, ctx, round_num=rnd)
        if not questions:
            break

        round_qa = dialogue.run_round(questions, ctx)
        all_raw_qa.extend(round_qa)
        print(f"  ✓ {len(round_qa)} QA pair(s) collected.")

    # ── all dialogue rounds done, now extract knowledge ──────
    if all_raw_qa:
        print(f"\n{'─'*40}  Knowledge extraction ({len(all_raw_qa)} QA pairs)")
        final_units = extractor.extract(all_raw_qa)
        schema      = updater.apply(schema, final_units)
        print(f"  ✓ {len(final_units)} representative unit(s) written to schema.")

    # ── version bump + revision_history ─────────────────────
    schema = append_revision(schema, cfg, session_id)

    # ── save raw dialogue log ────────────────────────────────
    log_path = target.parent / f"{target.stem}_dialogue_{session_id}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({
            "session_id":  session_id,
            "task_name":   task_name,
            "source_file": str(target),
            "timestamp":   datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "raw_qa":      all_raw_qa,
        }, f, ensure_ascii=False, indent=2)
    print(f"  ✓ Dialogue log: {log_path}")

    # ── save in-place ────────────────────────────────────────
    with open(target, "w", encoding="utf-8") as f:
        json.dump(schema, f, ensure_ascii=False, indent=2)

    new_ver = schema["document"]["version"]
    print(f"\n{'='*62}")
    print(f" ✓ Saved  : {target}")
    print(f" Version  : {new_ver}")
    print(f" Session  : {session_id}")
    print(f" QA pairs : {len(all_raw_qa)}")
    print(f" Units    : {schema['document'].get('knowledge_units_added', 0)}")
    print(f"{'='*62}\n")


# ============================================================
# ENTRY POINT
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(f"Usage: python {Path(__file__).name} data/<file>.json [--real] [--no-semantic]")

    _path   = sys.argv[1]
    _real   = "--real"        in sys.argv
    _no_sem = "--no-semantic" in sys.argv

    run_pipeline(_path, simulate=not _real, semantic_check=not _no_sem)
