from __future__ import annotations

import sys

from cosmic_resolve.model_provider import RuleBasedModelProvider
from cosmic_resolve.workflow import propose_resolution


def main() -> None:
    """Propose a resolution for each sample case. Nothing is executed without a human approval.

    Default uses the offline rule-based provider. Pass --bedrock for live Bedrock calls
    (needs BEDROCK_INFERENCE_PROFILE, AWS_REGION and an AWS login).
    """
    if "--bedrock" in sys.argv:
        from cosmic_resolve.bedrock_provider import BedrockModelProvider

        provider = BedrockModelProvider()
        print(f"Provider: Bedrock ({provider.model_id})")
    else:
        provider = RuleBasedModelProvider()
        print("Provider: offline rule-based")

    for case_id in ("C-1001", "C-1002", "C-1003"):
        run = propose_resolution(case_id, provider)
        proposal = run.proposal
        if proposal:
            print(f"{case_id}: {run.status} - {proposal.decision.value} ${proposal.amount:.2f} {proposal.policy_clause_ids}")
            for reason in proposal.escalation_reasons:
                print(f"    reason: {reason}")
        else:
            print(f"{case_id}: {run.status} - {run.error}")
        if run.status == "VALIDATION_FAILED":
            print(f"    validator: {run.error}")


if __name__ == "__main__":
    main()
