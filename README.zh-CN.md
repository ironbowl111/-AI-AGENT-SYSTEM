[日本語](README.md) · [English](README.en.md) · **简体中文**

# EKE-OP 生成流水线

以 AO-OP（由视频生成的动作观察作业手册）为起点，沿 CTA（认知任务分析）的观点空间与作业者对话，
生成 EKE-OP（熟练知识扩充作业手册）。

对应研究计划「研究具体方案 2026-9-9」中的处理步骤 ①〜⑨。⑩ 评估尚未实现。

---

## 使用方法

```bash
pip install -r requirements.txt
cp .env.example .env          # 填入 API_KEY

python main.py --only-scoring          # 只运行到 ① 评分并可视化（研讨会用）
python main.py --mode sim              # 用模拟作业者跑 1 个周期的 ①②
python main.py --mode real             # 真实作业者在终端中回答
python main.py --mode sim --cycles 2   # 跑 2 个周期以确认继承
```

其他参数：`--run <ID>`（运行 ID，作为 `runs/` 下的文件夹名，默认 `run_001`），
`--aoop <name>`（`data/` 下的 AO-OP 文件名，不含扩展名，默认 `aoop_v1`）。

## 输出（outputs/）

| 文件 | 内容 |
|---|---|
| `<run>_config.md` | 配置内容，附各值的出处（9/2／CTA 一般／设计判断） |
| `<run>_scoring.md` | ① 评分结果。open 单元格的前几名及按五个来源的分解 |
| `<run>_scoring.html` | ① step × 探针的热力图。可在浏览器中打开并贴到幻灯片 |
| `<run>_dialogue.md` | ② 对话记录。每一轮的提问、回答及 3 轴判定 |
| `<run>_ekeop.json` | 最终成果。`dialogue` 中也包含对话记录 |

`runs/` 和 `outputs/` 含有运行数据，已通过 `.gitignore` 排除在 git 之外。

## 与两阶段结构的对应（9/22 MTG）

- **事前分析**（由人进行，1 次）＝ 确定 `config/*.yaml`。程序不执行此阶段
- **主分析 ① 评分** ＝ `align.py` → `label.py` → `scoring.py`
- **主分析 ② 问题生成与对话** ＝ `dialogue.py` → `extract.py`

## 9/2 访谈结果在代码中的位置

即 `config/*.yaml` 中所有标有 `【出典：事前分析＝9/2】`（出处：事前分析＝9/2）的块。

| 位置 | 内容 | 作用方式 |
|---|---|---|
| `probes.yaml` 的 `probe_prior` | 各探针的命中件数（58 项标注） | 作为优先度加到所有 step |
| `probes.yaml` 的 `interview_example` | 各探针实际得到的回答示例 | 作为参考传入问题生成提示词 |
| `scoring.yaml` 的 `sop_rationale_probes` | 「SOP 记述的依据」来源 | 对存在对应 SOP 项的 step 加分 |
| `settings.yaml` 的 `free_input` | 鼓励自发补充的话术（22/58 件＝38%） | 对话中每一轮都显示 |
| `settings.yaml` 的 `closing_questions` | 结尾的开放式问题（1 个问题得到 3 条框外知识） | 固定放在对话最后 |
| `rubric.yaml` 的 `terminal_states` | 「没有理由」等终止状态（04・06・07） | 防止追问空转 |

---

## ★ 由人修改的四个地方

不读代码也想改变行为时，只需改这几处。

| 位置 | 内容 | 何时修改 |
|---|---|---|
| `config/*.yaml` | **判断标准本身**。8 个观点的定义、来源→观点对应表、3 轴评分标准 | 这是研究的贡献物。在此写入与定义文档相同的内容 |
| `prompts/*.txt` | 提示词模板 | 想改变提问措辞或输出格式时 |
| `core/llm.py` | **唯一调用模型的地方** | 更换模型、调整温度 |
| `storage/store.py` | **唯一读写本地文件的地方** | 更改保存位置、文件名 |

---

## 目录结构

```
config/     判断标准（设计时确定一次，运行时不变）
  probes.yaml    8 个观点的定义与提问方向
  scoring.yaml   来源→观点对应表、权重
  rubric.yaml    深度判定的 3 轴与终止状态
  settings.yaml  预算、追问上限、自发发言话术

prompts/    提示词模板（与代码分离）

core/       处理逻辑。与研究计划中的编号一一对应
  llm.py        模型调用
  eventlog.py   事件日志与投影（覆盖矩阵由此计算）
  align.py      ③ SOP–AO-OP 对应
  label.py      ④ step 观点标注
  scoring.py    ⑤ 分数合成与单元格选择（不调用模型）
  dialogue.py   ⑥ 提问、追问、自发发言
  extract.py    ⑨ 知识抽取与 EKE-OP 生成
  report.py     可视化报告（不调用模型）

storage/    文件输入输出
data/       输入（只读）: sop.json, aoop.json
runs/       各周期的中间结果（可删除后重新运行）
outputs/    成果物
```

---

## 设计约定

**事件日志是唯一的真实来源**
覆盖矩阵不作为变量保存，而是每次从 `events.jsonl` 投影计算。
可以恢复任意时刻的状态，能解释为什么提出某个问题，中途中断也能继续。

**不改写 AO-OP**
输入是只读的。EKE-OP 作为另一个独立产物生成。改写输入会导致无法追溯出处。

**LLM 判断语义，规则判断字面**
传给 `label.py` 的只有 `action` 文本。`on_failure` 等字段只由 `scoring.py` 的「记述密度」查看。
若两边都看，同一个依据会被重复计算。

**不丢弃无法归入 8 个观点的知识**
放入 `unclassified`。在 9/2 的试点中，有 15 条、9 种类型属于此类。
硬塞进固定结构虽能保留知识，却会丢失「它属于什么类型」这一信息。

**「没有理由」不是浅层回答，而是终点**
见 `rubric.yaml` 的 `terminal_states`。不加区分地追问会导致空转。
输出中也保留该状态：「问了但没有理由」与「还没问」是两回事。

**作业者的自发发言不消耗预算**
在 9/2 中，22/58 条知识（38%）来自这一途径。
删除 `settings.yaml` 中的 `free_input`，这 38% 会全部丢失。

---

## 如何阅读输出

`outputs/<run>_ekeop.json`

- `steps[].knowledge[]` — 按观点整理的知识项
- `unclassified[]` — 未能归入 8 个观点的项，`note` 中说明原因
- `coverage` — 每个单元格的 `open` / `probed` / `closed` 及终止状态
- `stats.untraceable_items` — **在转写文本中找不到出处的项数＝疑似幻觉**

若 `untraceable_items` 不为 0，说明抽取阶段写入了未曾说过的内容。
这也是作为评估指标需要报告的值。

---

## 尚未实现（研究计划 第 10 节）

评估模块：人类基线覆盖率、幻觉率、作业者审阅的修正率、
LLM-as-a-Judge（判定模型须与生成模型为不同系列）。
设计上可直接复用 `config/rubric.yaml` 作为评分标准。
