[日本語](README.md) · **English** · [简体中文](README.zh-CN.md)

# EKE-OP Generation Pipeline

Starting from an AO-OP (an action-observation operating procedure generated from video),
the pipeline interviews the worker along the CTA (Cognitive Task Analysis) probe space
and generates an EKE-OP (Expert-Knowledge-Enriched Operating Procedure).

Corresponds to processing steps ①–⑨ of the research plan "研究具体方案 2026-9-9".
Step ⑩ (evaluation) is not yet implemented.

---

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env          # write your API_KEY

python main.py --only-scoring          # stop after ① scoring and visualize (for lab meetings)
python main.py --mode sim              # one cycle of ①② with a simulated worker
python main.py --mode real             # a real worker answers in the terminal
python main.py --mode sim --cycles 2   # run 2 cycles to check inheritance
```

Other options: `--run <ID>` (run ID, used as the folder name under `runs/`; default `run_001`),
`--aoop <name>` (AO-OP file under `data/` without extension; default `aoop_v1`).

## Outputs (outputs/)

| File | Contents |
|---|---|
| `<run>_config.md` | Configuration contents, with the source of each value (9/2 / general CTA / design decision) |
| `<run>_scoring.md` | ① Scoring results: top open cells and the breakdown by the five sources |
| `<run>_scoring.html` | ① Step × probe heat map. Open it in a browser and paste into slides |
| `<run>_dialogue.md` | ② Dialogue log: question, answer and 3-axis judgment for every turn |
| `<run>_ekeop.json` | Final deliverable. Also contains the dialogue log under `dialogue` |

`runs/` and `outputs/` are excluded from git (`.gitignore`) because they contain run data.

## Mapping to the two-stage structure (9/22 MTG)

- **Pre-analysis** (by a human, once) = deciding `config/*.yaml`. The program does not run this stage
- **Main analysis ① Scoring** = `align.py` → `label.py` → `scoring.py`
- **Main analysis ② Question generation & dialogue** = `dialogue.py` → `extract.py`

## Where the 9/2 interview results enter the code

Every block in `config/*.yaml` marked `【出典：事前分析＝9/2】` (source: pre-analysis = 9/2).

| Location | Contents | Effect |
|---|---|---|
| `probe_prior` in `probes.yaml` | Number of hits per probe (annotation of 58 items) | Added to every step as a priority |
| `interview_example` in `probes.yaml` | Example answers actually given for each probe | Passed to the question-generation prompt as reference |
| `sop_rationale_probes` in `scoring.yaml` | "Rationale of SOP description" source | Bonus for steps that have a corresponding SOP item |
| `free_input` in `settings.yaml` | Wording that encourages spontaneous remarks (22/58 items = 38%) | Shown on every turn during the dialogue |
| `closing_questions` in `settings.yaml` | Open questions at the end (one question yielded 3 out-of-frame items) | Always placed at the end of the dialogue |
| `terminal_states` in `rubric.yaml` | Terminal states such as "no reason" (04, 06, 07) | Stops follow-up questions from spinning in place |

---

## ★ The four places humans edit

If you want to change behavior without reading the code, these are the only places to touch.

| Location | Contents | When to edit |
|---|---|---|
| `config/*.yaml` | **The judgment criteria themselves**: definitions of the 8 probes, source→probe mapping, 3-axis rubric | This is a research contribution. Write the same content as the definition documents here |
| `prompts/*.txt` | Prompt templates | To change question wording or output format |
| `core/llm.py` | **The only place that calls the model** | Swapping the model, adjusting temperature |
| `storage/store.py` | **The only place that touches local files** | Changing storage locations or file names |

---

## Directory layout

```
config/     Judgment criteria (decided once at design time; not changed at run time)
  probes.yaml    Definitions of the 8 probes and question directions
  scoring.yaml   Source→probe mapping, weights
  rubric.yaml    3 axes of depth judgment and terminal states
  settings.yaml  Budget, follow-up limits, spontaneous-remark wording

prompts/    Prompt templates (kept separate from the code)

core/       Processing. One-to-one with the numbers in the research plan
  llm.py        Model calls
  eventlog.py   Event log and projections (the coverage matrix is computed from here)
  align.py      ③ SOP–AO-OP alignment
  label.py      ④ Step probe labeling
  scoring.py    ⑤ Score synthesis and cell selection (does not call the model)
  dialogue.py   ⑥ Questions, follow-ups, spontaneous remarks
  extract.py    ⑨ Knowledge extraction and EKE-OP generation
  report.py     Visualization reports (does not call the model)

storage/    File I/O
data/       Inputs (read-only): sop.json, aoop.json
runs/       Intermediate state per cycle (safe to delete and re-run)
outputs/    Deliverables
```

---

## Design commitments

**The event log is the single source of truth**
The coverage matrix is not held as a variable; it is projected from `events.jsonl` every time.
The state at any point can be restored, every question can be explained, and an interrupted run can be resumed.

**The AO-OP is never rewritten**
Inputs are read-only. The EKE-OP is built as a separate artifact. Rewriting the input would make provenance untraceable.

**The LLM judges meaning; rules judge the literal text**
Only the `action` text is passed to `label.py`. Fields such as `on_failure` are seen only by the
"description density" source in `scoring.py`. Showing them to both would count the same evidence twice.

**Knowledge that does not fit the 8 probes is not thrown away**
It goes into `unclassified`. In the 9/2 pilot, 15 items of 9 types fell here.
Forcing them into a fixed schema keeps the knowledge but loses the information about what type it is.

**"No reason" is an endpoint, not a shallow answer**
See `terminal_states` in `rubric.yaml`. Following up without distinguishing this leads to spinning in place.
The state is kept in the output too: "asked, but there is no reason" differs from "not yet asked".

**Spontaneous remarks by the worker do not consume the budget**
On 9/2, 22/58 knowledge items (38%) came through this route.
Removing `free_input` from `settings.yaml` drops this entire 38%.

---

## Reading the output

`outputs/<run>_ekeop.json`

- `steps[].knowledge[]` — knowledge items per probe
- `unclassified[]` — items that did not fit the 8 probes; `note` explains why
- `coverage` — `open` / `probed` / `closed` and terminal state per cell
- `stats.untraceable_items` — **number of items whose source cannot be found in the transcript = suspected hallucinations**

If `untraceable_items` is not 0, the extraction stage wrote something that was not said.
This is also a value to report as an evaluation metric.

---

## Not yet implemented (research plan, section 10)

Evaluation module: human-baseline coverage rate, hallucination rate, correction rate under worker review,
and LLM-as-a-Judge (the judge model must be from a different family than the generation model).
It is designed so that `config/rubric.yaml` can be reused as-is for the rubric.
