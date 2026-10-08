"""
core/llm.py

★★★【モデルを呼ぶのはこのファイルだけ】★★★

モデルを差し替えたいとき、API のベース URL を変えたいとき、
温度やトークン数を調整したいときは、ここだけ直せば済みます。

環境変数（.env を参照）:
  API_KEY   必須
  BASE_URL  OpenAI 互換エンドポイント。省略時は OpenAI 本体
  MODEL     省略時は gpt-4o-mini
"""

import json
import os
import re
import time

from openai import OpenAI


class LLM:
    """モデル呼び出しの薄いラッパ。呼び出し回数を数えて最後に表示する。"""

    def __init__(self, model=None, temperature=0.3):
        key = os.getenv("API_KEY")
        if not key:
            raise RuntimeError("API_KEY が設定されていません（.env を確認）")
        self.client = OpenAI(
            api_key=key,
            base_url=os.getenv("BASE_URL", "https://api.openai.com/v1"),
        )
        self.model = model or os.getenv("MODEL", "gpt-4o-mini")
        self.temperature = float(os.getenv("TEMPERATURE", temperature))
        self.calls = 0
        self.log_path = None          # set_log_path() で指定されるまで記録しない

    def set_log_path(self, path):
        """生プロンプトと生応答の記録先を指定する。

        ラベルが定数化したり出力例が丸写しされたりしたとき、
        モデルが実際に何を受け取って何を返したかを後から確認できる唯一の材料。
        既存ファイルがあれば消して作り直す（1 run 1 ファイル）。
        """
        self.log_path = path
        if path.exists():
            path.unlink()

    def chat(self, system, user, max_tokens=1200, _kind=None):
        """1 往復の呼び出し。文字列を返す。"""
        self.calls += 1
        t0 = time.time()
        r = self.client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        out = r.choices[0].message.content.strip()
        self._log(_kind or "chat", system, user, out, time.time() - t0)
        return out

    def chat_json(self, system, user, max_tokens=2000, fallback=None):
        """JSON を期待する呼び出し。コードフェンスを剥がしてパースする。

        パースに失敗したら fallback を返す（例外で止めない）。
        モデルの気まぐれで 1 回失敗しても対話全体が落ちないようにするため。
        """
        raw = self.chat(system + "\n\nJSON のみを出力すること。", user,
                        max_tokens, _kind="chat_json")
        try:
            return json.loads(_strip_fence(raw))
        except json.JSONDecodeError:
            # パース失敗を記録する。fallback（全 0 など）が返ると
            # 結果だけ見ても失敗に気づけないため。
            self._log("parse_error", "", "", raw, 0.0)
            return fallback if fallback is not None else {"_parse_error": raw[:300]}

    def _log(self, kind, system, user, response, elapsed):
        """1 呼び出し分を JSONL に追記する。記録先が未設定なら何もしない。"""
        if self.log_path is None:
            return
        rec = {
            "n": self.calls,
            "kind": kind,
            "ts": round(time.time(), 3),
            "elapsed_s": round(elapsed, 2),
            "model": self.model,
            "temperature": self.temperature,
            "system": system,
            "user": user,
            "response": response,
        }
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _strip_fence(text):
    """```json ... ``` のコードフェンスを取り除く。"""
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.S)
    return m.group(1) if m else text
