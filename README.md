<div align="center">

# Theme B — Expert Dialogue Pipeline

**AI-Driven Expert Knowledge Extraction for Work Manual Refinement**

<br>

[中文](#中文) · [日本語](#日本語) · [English](#english)

</div>

---

<a name="中文"></a>

## 中文

### 项目简介

本系统通过模拟或真实的专家对话，自动检测作业手册中的知识缺口，并将提取的专家暗默知填写回手册 JSON 文件。理论基础为认知任务分析（CTA）中的 CPP（Clark, 2004）与 CDM（Klein et al., 1989）结构化探针方法。

### 目录结构

```
项目根目录/
├── env/
│   └── env              ← API 密钥与服务商配置
├── data/
│   └── *.json           ← 作业手册 JSON（原地更新）
└── theme_b_pipeline.py  ← 主程序
```

### 环境配置

在 `env/env` 文件中填写以下内容：

```ini
# OpenAI
PROVIDER=openai
API_KEY=sk-xxxxxxxxxxxxxxxx
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o-mini
EXPERT_ID=EXP-001

# 阿里云 Qwen（示例）
PROVIDER=qwen
API_KEY=sk-xxxxxxxxxxxxxxxx
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL=qwen-plus
EXPERT_ID=EXP-001
```

> 支持所有兼容 OpenAI Chat Completions API 的服务商。

### 安装依赖

```bash
pip install openai python-dotenv sentence-transformers scikit-learn numpy
```

### 使用方法

```bash
# 模拟专家模式（默认）
python theme_b_pipeline.py data/my_task.json

# 真实专家输入模式（在终端手动输入回答）
python theme_b_pipeline.py data/my_task.json --real

# 跳过语义模糊性检测（节省 token）
python theme_b_pipeline.py data/my_task.json --no-semantic
```

### 流程说明

```
JSON 手册
   │
   ├─ [Gap Detector] 结构性缺口检测 + 语义模糊性检测
   │
   ├─ [Question Generator] CTA 探针问题生成（CPP/CDM 框架）
   │       └─ 4 阶段递进：全体像 → 技法 → 基准 → 例外
   │
   ├─ [Dialogue Manager] 多轮对话（模拟 or 真实专家）
   │       └─ 含 Echo-Confirm 机制确认关键信息
   │
   ├─ [QA Pair Extractor] 三段式知识提取
   │       ├─ Stage 1: LLM 将对话整理为结构化知识单元
   │       ├─ Stage 2: BGE 嵌入 + DBSCAN 聚类去重
   │       └─ Stage 3: LLM 合并同簇知识为代表项
   │
   └─ [Manual Updater] 将知识单元写回 JSON + 版本号递增
```

### 输出文件

| 文件 | 说明 |
|------|------|
| `data/my_task.json` | 原地更新，新增知识字段，版本号递增 |
| `data/my_task_dialogue_<session_id>.json` | 原始对话记录存档 |

### 主要参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MAX_ROUNDS` | 3 | 最大对话轮次 |
| `Q_PER_ROUND` | 3 | 每轮最大问题数 |
| `EMBED_MODEL` | `bge-small-en-v1.5` | 语义嵌入模型 |
| `DBSCAN_EPS` | 0.30 | 聚类距离阈值（越大合并越激进） |
| `DBSCAN_MIN_PTS` | 2 | 形成簇的最小样本数 |

---

<a name="日本語"></a>

## 日本語

### プロジェクト概要

本システムは、シミュレーションまたは実際の専門家との対話を通じて、作業手順書の知識ギャップを自動検出し、抽出した暗黙知を手順書 JSON ファイルに書き戻します。理論的基盤は、認知タスク分析（CTA）の CPP（Clark, 2004）および CDM（Klein et al., 1989）構造化プローブ手法です。

### ディレクトリ構成

```
プロジェクトルート/
├── env/
│   └── env              ← API キーとプロバイダ設定
├── data/
│   └── *.json           ← 作業手順書 JSON（上書き更新）
└── theme_b_pipeline.py  ← メインスクリプト
```

### 環境設定

`env/env` ファイルに以下を記載してください：

```ini
# OpenAI
PROVIDER=openai
API_KEY=sk-xxxxxxxxxxxxxxxx
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o-mini
EXPERT_ID=EXP-001

# Alibaba Cloud Qwen（例）
PROVIDER=qwen
API_KEY=sk-xxxxxxxxxxxxxxxx
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL=qwen-plus
EXPERT_ID=EXP-001
```

> OpenAI Chat Completions API 互換のプロバイダであれば使用可能です。

### 依存パッケージのインストール

```bash
pip install openai python-dotenv sentence-transformers scikit-learn numpy
```

### 使い方

```bash
# 専門家シミュレーションモード（デフォルト）
python theme_b_pipeline.py data/my_task.json

# 実際の専門家入力モード（ターミナルで手動入力）
python theme_b_pipeline.py data/my_task.json --real

# 意味的曖昧性検出をスキップ（トークン節約）
python theme_b_pipeline.py data/my_task.json --no-semantic
```

### パイプライン説明

```
手順書 JSON
   │
   ├─ [Gap Detector] 構造的ギャップ検出 + 意味的曖昧性検出
   │
   ├─ [Question Generator] CTA プローブ質問生成（CPP/CDM フレームワーク）
   │       └─ 4段階進行：全体像 → 技法 → 基準 → 例外
   │
   ├─ [Dialogue Manager] 多ラウンド対話（シミュレーションまたは実専門家）
   │       └─ Echo-Confirm 機構による重要情報の確認
   │
   ├─ [QA Pair Extractor] 3段階知識抽出
   │       ├─ Stage 1: LLM が対話を構造化知識ユニットに整理
   │       ├─ Stage 2: BGE 埋め込み + DBSCAN クラスタリングによる重複除去
   │       └─ Stage 3: LLM が同クラスタの知識を代表項目に統合
   │
   └─ [Manual Updater] 知識ユニットを JSON に書き戻し + バージョン番号インクリメント
```

### 出力ファイル

| ファイル | 説明 |
|----------|------|
| `data/my_task.json` | 上書き更新、新規知識フィールド追加、バージョン番号インクリメント |
| `data/my_task_dialogue_<session_id>.json` | 生の対話ログアーカイブ |

### 主要パラメータ

| パラメータ | デフォルト値 | 説明 |
|-----------|-------------|------|
| `MAX_ROUNDS` | 3 | 最大対話ラウンド数 |
| `Q_PER_ROUND` | 3 | 1ラウンドあたりの最大質問数 |
| `EMBED_MODEL` | `bge-small-en-v1.5` | 意味埋め込みモデル |
| `DBSCAN_EPS` | 0.30 | クラスタリング距離閾値（大きいほど積極的に統合） |
| `DBSCAN_MIN_PTS` | 2 | クラスタ形成に必要な最小サンプル数 |

### 知識ギャップの種別

| `gap_type` | 意味 | CTA プローブ手法 |
|------------|------|----------------|
| `judgment_criterion` | 判断基準が不明確 | 知覚的手がかり抽出 |
| `sensory_cue` | 感覚的情報の記述不足 | 感覚的情報抽出 |
| `exception_handling` | 例外処理が未記載 | 例外・意思決定抽出 |
| `expert_tip` | 専門家の暗黙知が欠如 | 暗黙知・技法抽出 |
| `precondition` | 前提条件が不明 | 前提条件抽出 |
| `completion_standard` | 完了基準が不明確 | 完了基準抽出 |
| `quality_check` | 品質確認手順が欠如 | 品質確認手順抽出 |
| `safety_note` | 安全上の注意が欠如 | 安全リスク抽出 |

---

<a name="english"></a>

## English

### Overview

This system automatically detects knowledge gaps in work procedure manuals and fills them in by running simulated or real expert dialogues. Extracted tacit knowledge is written back into the manual's JSON file. The theoretical foundation is Cognitive Task Analysis (CTA) using CPP (Clark, 2004) and CDM (Klein et al., 1989) structured probes.

### Directory Layout

```
project-root/
├── env/
│   └── env              ← API key and provider settings
├── data/
│   └── *.json           ← Work procedure JSON files (updated in-place)
└── theme_b_pipeline.py  ← Main script
```

### Configuration

Fill in `env/env`:

```ini
# OpenAI
PROVIDER=openai
API_KEY=sk-xxxxxxxxxxxxxxxx
BASE_URL=https://api.openai.com/v1
MODEL=gpt-4o-mini
EXPERT_ID=EXP-001

# Alibaba Cloud Qwen (example)
PROVIDER=qwen
API_KEY=sk-xxxxxxxxxxxxxxxx
BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MODEL=qwen-plus
EXPERT_ID=EXP-001
```

> Any provider compatible with the OpenAI Chat Completions API is supported.

### Install Dependencies

```bash
pip install openai python-dotenv sentence-transformers scikit-learn numpy
```

### Usage

```bash
# LLM-simulated expert mode (default)
python theme_b_pipeline.py data/my_task.json

# Real expert input mode (answer questions manually in the terminal)
python theme_b_pipeline.py data/my_task.json --real

# Skip semantic vagueness detection (saves tokens)
python theme_b_pipeline.py data/my_task.json --no-semantic
```

### Pipeline Architecture

```
Procedure JSON
   │
   ├─ [Gap Detector] Structural gap detection + semantic vagueness detection
   │
   ├─ [Question Generator] CTA probe question generation (CPP/CDM framework)
   │       └─ 4-stage progression: overview → techniques → criteria → exceptions
   │
   ├─ [Dialogue Manager] Multi-round dialogue (simulated or real expert)
   │       └─ Echo-Confirm mechanism to verify key information
   │
   ├─ [QA Pair Extractor] 3-stage knowledge extraction
   │       ├─ Stage 1: LLM restructures dialogue into structured knowledge units
   │       ├─ Stage 2: BGE embedding + DBSCAN clustering for deduplication
   │       └─ Stage 3: LLM merges same-cluster units into a representative item
   │
   └─ [Manual Updater] Writes knowledge units back into JSON + bumps version number
```

### Output Files

| File | Description |
|------|-------------|
| `data/my_task.json` | Updated in-place with new knowledge fields and incremented version |
| `data/my_task_dialogue_<session_id>.json` | Raw dialogue log archive |

### Key Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `MAX_ROUNDS` | 3 | Maximum dialogue rounds per run |
| `Q_PER_ROUND` | 3 | Maximum questions per round |
| `EMBED_MODEL` | `bge-small-en-v1.5` | Sentence embedding model (swap to `bge-large-en-v1.5` for higher accuracy) |
| `DBSCAN_EPS` | 0.30 | Cosine-distance threshold for clustering (higher = merge more aggressively) |
| `DBSCAN_MIN_PTS` | 2 | Minimum samples required to form a cluster |

### Knowledge Gap Types

| `gap_type` | Meaning | CTA Probe Method |
|------------|---------|-----------------|
| `judgment_criterion` | Unclear judgment criterion | Perceptual cue elicitation |
| `sensory_cue` | Missing sensory information | Sensory information extraction |
| `exception_handling` | Missing failure handling | Exception & decision elicitation |
| `expert_tip` | Missing expert tacit knowledge | Tacit knowledge & technique extraction |
| `precondition` | Unclear preconditions | Precondition extraction |
| `completion_standard` | Unclear completion standard | Completion criterion extraction |
| `quality_check` | Missing quality check procedure | Quality check extraction |
| `safety_note` | Missing safety notes | Safety risk extraction |

### References

- Clark, R. E. (2004). *Cognitive Task Analysis for Expert-Based Instruction in Healthcare.*
- Klein, G. A., Calderwood, R., & MacGregor, D. (1989). *Critical Decision Method for Eliciting Knowledge.* IEEE Transactions on Systems, Man, and Cybernetics.
- Clark, R. E., & Elen, J. (2006). *When less is more: Research and theory insights about instruction for complex learning.*

---

<div align="center">
<sub>回到顶部 / トップへ戻る / Back to top: <a href="#中文">中文</a> · <a href="#日本語">日本語</a> · <a href="#english">English</a></sub>
</div>
