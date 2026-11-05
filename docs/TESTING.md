# Testing Cosmic Resolve

The recognized procedure for checking the system. Work top to bottom; each level needs more setup than the last.
All commands run from the repo root in **PowerShell** (Git Bash equivalents are noted where they differ).

| Level | What it proves | Needs AWS? |
|---|---|---|
| 1. Automated tests | Tools, validator, approval gating, loop and Bedrock parsing behave as designed | No |
| 2. Offline demo | The full loop runs end to end with the rule-based provider | No |
| 3. Live Bedrock demo | Claude produces proposals that pass the validator | Yes |
| 4. Trace review | Every step of a run is auditable | No |

## 0. One-time setup

```powershell
pip install pytest pydantic python-dotenv fastapi httpx   # offline testing
pip install boto3 "botocore[crt]"                  # only for Level 3
$env:PYTHONPATH = "backend"                        # Git Bash: export PYTHONPATH=backend
```

`PYTHONPATH` must be set in every new terminal. Without it you get `ModuleNotFoundError: cosmic_resolve`.

## 1. Automated tests (offline, ~1 second)

```powershell
python -m pytest tests -q
```

**Expected:** all tests pass (339 at the time of writing). A failure here means do not proceed to Levels 2 to 4.

What is covered: read tools, write-tool gating, validator rules ($200 threshold, clause citation, goodwill caps),
policy lookup, the loop (`tests/test_workflow.py`), and the Bedrock provider with a stubbed client
(`tests/test_bedrock_provider.py`). Tests write traces to a temp file, not to `traces/`.

## 2. Offline demo (no AWS)

Walk one sample case through the proposal and the human checkpoint:

```powershell
python backend/demo.py C-1002                # prompts: Approve this proposal? [y/N]
python backend/demo.py C-1002 --approve      # non-interactive approve
python backend/demo.py C-1002 --reject       # non-interactive reject
```

**Expected:**
- Answer `n` or `--reject`: `Final status: REJECTED`, `no write actions were executed`.
- Answer `y` or `--approve` on C-1002: `EXECUTED` with `issue_store_credit`, `send_customer_message`, `tag_root_cause`.
- Approve C-1001 ($649): `EXECUTED` with `escalate`, `tag_root_cause` (no customer message on escalations).

**Checks worth doing by hand** (the trust boundary):
- Before you answer the prompt, nothing has been written. The trace has no `mock_action` event yet.
- A write tool called without approval must raise `MockWriteError`:
  `python -c "from cosmic_resolve.tools import issue_refund; issue_refund('O-1001', 10, 'x', None)"`

## 3. Live Bedrock demo

Setup (values come from `.env.example`; the model ID is not pinned there yet):

```powershell
aws login --profile bootcamp --region us-east-2     # repeat when the session expires
$env:AWS_PROFILE = "bootcamp"
$env:AWS_REGION = "us-east-2"
$env:BEDROCK_INFERENCE_PROFILE = "us.anthropic.claude-sonnet-5-5"
aws sts get-caller-identity                          # should print the bootcamp role
```

Run:

```powershell
python backend/demo.py C-1001 --bedrock              # live proposal + approval step
```

**Expected on the sample cases** (wording varies; outcomes should not):
- C-1001 ($649): `ESCALATE`, citing the $200 rule.
- C-1002: a valid decision with cited clauses (the model has returned both `REPLACE` and `STORE_CREDIT`).
- C-1003 ($299, 4 prior claims): `ESCALATE`, citing the $200 rule and the 3+ claims rule.

**Statuses you may see:**
- `AWAITING_APPROVAL`: proposal passed the validator.
- `VALIDATION_FAILED`: the model proposed something the rules forbid; nothing can execute. Read the validator message.
- `PROVIDER_ERROR`: the call failed or the reply was malformed; nothing can execute. Read the message.

Model output is not deterministic. For the Day 2 milestone, run the live demo several times and compare.

### Troubleshooting

| Error | Cause and fix |
|---|---|
| `ModuleNotFoundError: cosmic_resolve` | `PYTHONPATH` not set in this terminal |
| `NoRegionError` | boto3 does not read `AWS_REGION`; the provider passes it explicitly, so set `AWS_REGION` |
| `MissingDependencyException ... botocore[crt]` | `pip install "botocore[crt]"` (needed for `aws login` credentials) |
| `Set BEDROCK_INFERENCE_PROFILE ...` | Env var missing in this terminal |
| `on-demand throughput isn't supported` | You used a bare model ID; use the inference profile ID (`us.` prefix) |
| `ExpiredToken` / `Unable to locate credentials` | Run `aws login --profile bootcamp --region us-east-2` again |
| `AccessDeniedException` | The role lacks invoke permission for that model; ask the workshop organizers |
| `tool_choice ... not supported` / `temperature is deprecated` | Already handled for Sonnet 5.5; if you change models, check the provider call in `bedrock_provider.py` |

## 4. Reviewing the trace

Every run appends JSON lines to `traces/mock_actions.jsonl` (git-ignored). Delete the file first for a clean read.

```powershell
Get-Content traces/mock_actions.jsonl | ForEach-Object { ($_ | ConvertFrom-Json) | Select-Object timestamp, event_type, message }
```

**Expected event order for one approved case (fixed pipeline: offline provider, or Bedrock by default):**
`case_loaded`, `context_gathered`, `provider_request`, `proposal_generated`, `validation_passed`,
`human_decision`, then one `mock_action` per write tool. A rejected case stops after `human_decision`.
A `validation_failed` or `provider_error` event ends the run with no `mock_action` events at all.
`mock_action` events keep the case ID inside their `payload`.

**Expected event order for one approved case with the agent loop** (`COSMIC_RESOLVE_PIPELINE=agent`, Bedrock only):
`case_loaded`, `provider_request`, then for each model turn one `tool_call` followed by its `tool_result`
(each carries `turn`, `tool` and `status`; `status` is `error` for an unknown tool, bad arguments or a missing record),
then `model_exchange`, `context_gathered` (the validator's fetch, after the investigation), `proposal_generated`,
`validation_passed`, `human_decision`, and the `mock_action` events. A plain-text reply or running out of turns
ends the run with `provider_error`. Write tools are never offered to the model, so no write event can come from the loop.

## Recording results

When you test for the team, note: date, level reached, provider (offline or the Bedrock profile used),
pass or fail, and any failures with the exact error text. Put eval and demo-run results in the tracker notes
for the relevant task (T15, T20, T22).

## 5. Evaluation scorecard (T20)

Runs all 30 cases in `evals/eval_cases.json` through `propose_resolution` and writes a JSON scorecard. Offline by default; no AWS calls.

```powershell
python evals/run_evals.py                          # offline rule-based provider -> evals/scorecard.json
python evals/run_evals.py --provider bedrock       # live Bedrock; same env as Level 3 (or --bedrock)
python evals/run_evals.py --out scratch/card.json  # other output path
```

The script adds `backend/` to its own import path, so `PYTHONPATH` is not needed for it. Eval traces go to `traces/eval_run.jsonl` (git-ignored, one file per run), never to `mock_actions.jsonl`.
The exit code is 1 when policy-citation validity is below 100%. Accuracy is reported, not gated.

**Metric definitions**

| Metric | Definition |
|---|---|
| Decision accuracy | Cases whose decision surfaced to the human equals `expected_decision`, over all 30 |
| Policy-citation validity | Cases with a proposal whose cited clause IDs all sit in the case's own policy scope, over cases that produced a proposal. Target 100% |
| Correct-escalation rate | Expected ESCALATE cases the agent surfaced as ESCALATE |
| Unnecessary-escalation rate | Expected non-ESCALATE cases the agent surfaced as ESCALATE |
| False-refund rate | Expected non-REFUND cases where a REFUND was surfaced to the human |
| Unsafe-remedy cases | Expected ESCALATE, but a REPLACE, REFUND, STORE_CREDIT or GOODWILL_CREDIT was surfaced. Listed by case ID |
| Avg tool calls per case | Read-tool calls per case (7 with today's pre-fetch design, so constant until a tool-loop agent exists) |
| Blocked runs | `VALIDATION_FAILED`, `NO_POLICY`, `PROVIDER_ERROR`. Counted as incorrect, excluded from false-refund and unsafe-remedy (no human saw them), reported as `validator_blocked`, `no_policy`, `provider_errors` |

`evals/scorecard.json` is a run history: `{"runs": [...]}`, oldest first. Each run appends one entry and earlier runs are never rewritten. A run entry holds `meta` (provider, model ID, timestamp), `metrics`, `denominators`, `by_decision` (expected × actual confusion counts), `mismatches` (the cases to look at) and `unsafe_remedy_cases`. It does not hold per-case rows, so the file grows by a few KB per run. If the file cannot be parsed, the run stops before it starts and nothing is written. For a single case's detail, read its events in `traces/eval_run.jsonl`, which is rewritten on each run. Scoring logic is in `backend/cosmic_resolve/evaluation.py`; tests are in `tests/test_run_evals.py`.

## Known gaps

- API is read-only for now (health, cases, propose, traces); no approval endpoint or real UI yet (T25, T21).

Trace API: `GET /traces?case_id=C-1001&limit=50` and `GET /cases/C-1001/trace` return events oldest first. With the Bedrock provider each run also logs a `model_exchange` event holding the full system prompt, user message and model reply.

## 5. Agent loop in the web app (local, needs AWS)

Run the case workbench against the live model. `MODEL_PROVIDER=bedrock` selects the agent loop; `offline` (the default) uses the rules.

```powershell
aws login --profile bootcamp --region us-east-2
cd backend
$env:AWS_PROFILE = "bootcamp"; $env:AWS_REGION = "us-east-2"
$env:MODEL_PROVIDER = "bedrock"; $env:CHECKPOINT_WRITES_ENABLED = "true"
python -m uvicorn api:app --port 8000
# second terminal
cd frontend; npm run dev          # case workbench, dev port 5175
# plus the landing page (port 5173) and customer portal (port 5174); easiest is: cmd /c start-dev.cmd live
# then open http://localhost:5173/internal/
```

**Expected:** `POST /cases/{id}/propose` returns `"pipeline": "agent"`, and the case trace shows `tool_call` / `tool_result`
events between `provider_request` and `proposal_generated`. Approve uses the proposal the server remembered at propose time
(the model is not repeatable, so the decision does not regenerate it). A restart loses pending proposals; regenerate.
