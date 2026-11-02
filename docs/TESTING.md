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
pip install pytest pydantic python-dotenv          # offline testing
pip install boto3 "botocore[crt]"                  # only for Level 3
$env:PYTHONPATH = "backend"                        # Git Bash: export PYTHONPATH=backend
```

`PYTHONPATH` must be set in every new terminal. Without it you get `ModuleNotFoundError: cosmic_resolve`.

## 1. Automated tests (offline, ~1 second)

```powershell
python -m pytest tests -q
```

**Expected:** all tests pass (49 at the time of writing). A failure here means do not proceed to Levels 2 to 4.

What is covered: read tools, write-tool gating, validator rules ($200 threshold, clause citation, goodwill caps),
policy lookup, the loop (`tests/test_workflow.py`), and the Bedrock provider with a stubbed client
(`tests/test_bedrock_provider.py`). Tests write traces to a temp file, not to `traces/`.

## 2. Offline demo (no AWS)

Proposals for the three sample cases:

```powershell
python backend/app.py
```

**Expected:**
```
C-1001: AWAITING_APPROVAL - ESCALATE $649.00 [...]
C-1002: AWAITING_APPROVAL - STORE_CREDIT $45.00 [...]
C-1003: AWAITING_APPROVAL - ESCALATE $299.00 [...]
```

Walk one case through the human checkpoint:

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
python backend/app.py --bedrock                      # 3 live calls, nothing executed
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

**Expected event order for one approved case:**
`case_loaded`, `context_gathered`, `provider_request`, `proposal_generated`, `validation_passed`,
`human_decision`, then one `mock_action` per write tool. A rejected case stops after `human_decision`.
A `validation_failed` or `provider_error` event ends the run with no `mock_action` events at all.
`mock_action` events keep the case ID inside their `payload`.

## Recording results

When you test for the team, note: date, level reached, provider (offline or the Bedrock profile used),
pass or fail, and any failures with the exact error text. Put eval and demo-run results in the tracker notes
for the relevant task (T15, T20, T22).

## Known gaps

- Fixtures hold 3 orders, products and shipments (plus 150 customers) until T08 lands; only C-1001 to C-1003 run end to end.
- No prompt-injection case exists yet, so injection resistance is untested.
- `evals/run_evals.py` only checks that expected decisions are valid enum values. It is not a real evaluation (T20).
- `evals/eval_cases.json` expects REPLACE for $649 and REFUND for $299, which contradicts the $200 escalation rule.
- No FastAPI endpoints, trace endpoint or frontend yet.
