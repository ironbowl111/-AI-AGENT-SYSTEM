"""
storage/store.py

★★★【ローカルファイルを触るのはこのファイルだけ】★★★

保存場所を変えたいとき、ファイル名を変えたいときは、ここだけ直せば済みます。
他のモジュールは全部この関数経由でしかディスクに触りません。

  data/          入力。読み取り専用。消さないこと
  runs/<run>/cycle_<n>/   サイクルごとの途中経過。消して再実行してよい
  outputs/       成果物
"""

import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent   # eke_op/ ディレクトリ


# ------------------------------------------------------------------
# 設定・プロンプトの読み込み
# ------------------------------------------------------------------

def load_config(name):
    """config/<name>.yaml を読む。判断基準はすべてここから来る。"""
    with open(ROOT / "config" / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prompt(name):
    """prompts/<name>.txt を読む。

    ファイル先頭の注釈ブロック（# で始まる行が続く範囲）だけを落とす。
    本文中の見出し「## 対象ステップ」なども # で始まるため、
    行頭 # を無条件に落とすと見出しが全部消えてプロンプトが壊れる。
    """
    with open(ROOT / "prompts" / f"{name}.txt", encoding="utf-8") as f:
        lines = f.readlines()
    i = 0
    while i < len(lines) and lines[i].startswith("#"):   # 先頭の注釈だけ飛ばす
        i += 1
    return "".join(lines[i:]).strip()


# ------------------------------------------------------------------
# 入力（読み取り専用）
# ------------------------------------------------------------------

def load_input(name):
    """data/<name>.json を読む。SOP と AO-OP。書き換えないこと。"""
    with open(ROOT / "data" / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------
# サイクルごとの状態
# ------------------------------------------------------------------

def cycle_dir(run, cycle):
    """runs/<run>/cycle_<n>/ のパスを返し、無ければ作る。"""
    d = ROOT / "runs" / run / f"cycle_{cycle}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_state(run, cycle, name, obj):
    """途中経過を保存する（alignment / labels / ekeop など）。"""
    with open(cycle_dir(run, cycle) / f"{name}.json", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def load_state(run, cycle, name, default=None):
    """途中経過を読む。無ければ default を返す。"""
    p = cycle_dir(run, cycle) / f"{name}.json"
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_previous(run, cycle, name, default=None):
    """前サイクルの成果を読む。サイクル間の継承はこの関数が支えている。"""
    if cycle <= 1:
        return default
    return load_state(run, cycle - 1, name, default)


# ------------------------------------------------------------------
# イベントログ（追記のみ・唯一の真実源）
# ------------------------------------------------------------------

def append_event(run, cycle, event):
    """events.jsonl に 1 行追記する。既存行は絶対に書き換えない。"""
    with open(cycle_dir(run, cycle) / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events(run, cycle):
    """events.jsonl を全部読む。カバレッジ行列はここから投影して作る。"""
    p = cycle_dir(run, cycle) / "events.jsonl"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


# ------------------------------------------------------------------
# 出力
# ------------------------------------------------------------------

def save_text(name, text):
    """outputs/<name> にテキスト（Markdown / HTML）を書く。可視化レポート用。"""
    d = ROOT / "outputs"
    d.mkdir(exist_ok=True)
    path = d / name
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


def save_output(name, obj):
    """outputs/<name>.json に成果物を書く。"""
    d = ROOT / "outputs"
    d.mkdir(exist_ok=True)
    with open(d / f"{name}.json", "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    return d / f"{name}.json"
