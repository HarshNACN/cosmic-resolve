"""Interactive walkthrough of one case: propose -> human checkpoint -> gated writes -> trace.

Usage (from the repo root, with PYTHONPATH=backend):
    python backend/demo.py C-1002               # offline rule-based provider
    python backend/demo.py C-1002 --bedrock     # live Bedrock (see docs/TESTING.md for env setup)
    python backend/demo.py C-1002 --approve     # skip the prompt and approve
    python backend/demo.py C-1002 --reject      # skip the prompt and reject

Writes are mock-only; they append to traces/mock_actions.jsonl.
"""
from __future__ import annotations

import json
import sys

from cosmic_resolve.config import SETTINGS
from cosmic_resolve.bedrock_agent import select_provider
from cosmic_resolve.models import ApprovalDecision
from cosmic_resolve.workflow import AWAITING_APPROVAL, apply_approval, propose_resolution


def main(argv: list[str]) -> int:
    case_ids = [a for a in argv if not a.startswith("--")]
    if len(case_ids) != 1:
        print(__doc__)
        return 2
    case_id = case_ids[0]

    live = "--bedrock" in argv
    provider = select_provider(live)
    print(f"Provider: Bedrock ({provider.model_id})" if live else "Provider: offline rule-based")

    run = propose_resolution(case_id, provider)
    print(f"\nStatus: {run.status}")
    if run.proposal is None or run.status != AWAITING_APPROVAL:
        if run.error:
            print(f"Reason: {run.error}")
        if run.proposal is not None:
            print(json.dumps(run.proposal.model_dump(mode="json"), indent=2))
        return 1

    print(f"Complaint: {run.case.complaint_text}\n")
    print(json.dumps(run.proposal.model_dump(mode="json"), indent=2))

    if "--approve" in argv:
        approved = True
    elif "--reject" in argv:
        approved = False
    else:
        approved = input("\nApprove this proposal? [y/N] ").strip().lower() == "y"

    approval = ApprovalDecision(
        approved=approved,
        approved_by="demo-reviewer",
        approval_token="demo-approval-token",
        decision=run.proposal.decision if approved else None,
        notes="Decision made in demo.py",
    )
    run = apply_approval(run, approval)

    print(f"\nFinal status: {run.status}")
    for action in run.actions:
        print(f"  executed: {action['action']}")
    if not run.actions:
        print("  no write actions were executed")
    print(f"\nTrace file: {SETTINGS.trace_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
