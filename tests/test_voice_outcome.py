"""What a case has actually done, and what Cosmo may therefore say (voice/outcome.py).

The rule these protect: an approval is not an execution. "Resolved" needs the right action recorded by the write tools
themselves (with a matching real amount for money) and the checkpoint's closing summary. Approved-but-unconfirmed,
escalated, rejected and not-yet-reviewed cases must each stay distinct, and Cosmo announces only what is verified.
"""
import pytest

from cosmic_resolve import customer
from cosmic_resolve.checkpoint import decide, proposal_fingerprint, reset_decided_for_tests
from cosmic_resolve.config import SETTINGS
from cosmic_resolve.model_provider import RuleBasedModelProvider
from cosmic_resolve.models import CheckpointAction, DecisionRequest
from cosmic_resolve.tracing import append_case_event, read_trace_events
from cosmic_resolve.voice import agent_config as cfg
from cosmic_resolve.voice import store
from cosmic_resolve.voice.dialogue import check_outcome, run_turn, speak_outcome
from cosmic_resolve.voice.orders import customer_first_name, recent_orders
from cosmic_resolve.voice.outcome import APPROVED, FOLLOW_UP, RECEIVED, RESOLVED, UNDER_REVIEW, case_outcome
from cosmic_resolve.workflow import propose_resolution
from voice_events import approve, run_actions


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(SETTINGS, "trace_path", tmp_path / "trace.jsonl")
    monkeypatch.setenv("CHECKPOINT_WRITES_ENABLED", "true")
    monkeypatch.delenv(cfg.ENV_MULTILINGUAL, raising=False)
    store.reset()
    customer.reset_sessions_for_tests()
    reset_decided_for_tests()
    yield
    store.reset()
    customer.reset_sessions_for_tests()
    reset_decided_for_tests()


def new_case(issue="LATE_OR_MISSING", order="O-1002", customer_id="C-002"):
    request = customer.SupportIntakeRequest(order_reference=order, issue_type=issue, customer_statement="The smart plug never arrived.", channel="WEB")
    return store.get_case_record(customer.receive_intake(request, customer_id).reference)


def execute(case, decision="REPLACE", **kwargs):
    run_actions(case.case_id, case.order_id, case.customer_id, decision, **kwargs)


def state_of(case):
    return case_outcome(case.case_id).state


def test_a_case_walks_through_the_states_only_as_things_really_happen():
    case = new_case()
    assert state_of(case) == RECEIVED
    propose_resolution(case.case_id, RuleBasedModelProvider())
    assert state_of(case) == UNDER_REVIEW  # a recommendation exists for a person to review
    approve(case.case_id)
    assert state_of(case) == APPROVED  # approved, but nothing is confirmed done yet
    execute(case, "REPLACE", message="Your replacement ships today.")  # (a second approval record; the latest decision counts)
    outcome = case_outcome(case.case_id)
    assert outcome.state == RESOLVED and outcome.decision == "REPLACE" and outcome.message == "Your replacement ships today."


@pytest.mark.parametrize("decision, amount", [("REPLACE", None), ("REFUND", 45.0), ("STORE_CREDIT", 10), ("GOODWILL_CREDIT", 5.5)])
def test_every_resolving_decision_is_resolved_only_with_a_complete_execution(decision, amount):
    case = new_case()
    execute(case, decision, amount=amount)
    outcome = case_outcome(case.case_id)
    assert outcome.state == RESOLVED and outcome.decision == decision and outcome.amount == (float(amount) if amount else None)
    assert [a["action"] for a in outcome.executed][-1] == "tag_root_cause"


def test_approval_alone_is_not_resolved():
    case = new_case()
    approve(case.case_id)
    outcome = case_outcome(case.case_id)
    assert outcome.state == APPROVED and outcome.reason == "NOT_CONFIRMED"


def test_a_failure_part_way_leaves_the_case_approved_not_resolved():
    """The tools ran (or some did) but the closing summary was never written."""
    case = new_case()
    execute(case, "REFUND", amount=45.0, stop_before_summary=True)
    assert state_of(case) == APPROVED


@pytest.mark.parametrize(
    "problem",
    [
        {"unrecorded": ("create_replacement",)},  # the summary lists the replacement but the tool never recorded it
        {"unrecorded": ("send_customer_message",)},  # no customer message was actually sent
        {"unrecorded": ("tag_root_cause",)},
    ],
)
def test_a_summary_the_tools_records_do_not_back_up_is_not_confirmed(problem):
    case = new_case()
    execute(case, "REPLACE", **problem)
    assert state_of(case) == APPROVED


@pytest.mark.parametrize(
    "decision, amount, recorded",
    [
        ("REFUND", None, None),  # a refund with no amount
        ("REFUND", 0, None),
        ("REFUND", -5.0, None),
        ("REFUND", 45.0, 40.0),  # the tool recorded a different amount than the summary claims
        ("STORE_CREDIT", None, None),
    ],
)
def test_a_money_action_needs_the_same_real_amount_in_the_summary_and_the_tools_record(decision, amount, recorded):
    case = new_case()
    execute(case, decision, amount=amount, recorded_amount=recorded)
    assert state_of(case) == APPROVED


def test_an_unknown_decision_in_the_summary_is_never_resolved():
    case = new_case()
    execute(case, "REPLACE")
    append_case_event(case.case_id, "actions_executed", "again", decision="MAGIC", actions=[{"action": "create_replacement"}])
    assert state_of(case) == RESOLVED  # the first complete summary after the approval is the one that counts
    other = new_case()
    approve(other.case_id)
    append_case_event(other.case_id, "actions_executed", "bogus", decision="MAGIC", actions=[{"action": "create_replacement"}])
    assert state_of(other) == APPROVED


def test_a_rejection_and_an_escalation_are_follow_ups_and_neither_is_a_resolution():
    rejected = new_case()
    execute(rejected, approved=False)
    assert case_outcome(rejected.case_id).state == FOLLOW_UP and case_outcome(rejected.case_id).reason == "REJECTED"

    escalated = new_case()
    execute(escalated, "ESCALATE")
    outcome = case_outcome(escalated.case_id)
    assert outcome.state == FOLLOW_UP and outcome.reason == "ESCALATED" and outcome.decision == "ESCALATE"

    unconfirmed = new_case()
    execute(unconfirmed, "ESCALATE", unrecorded=("escalate",))
    assert state_of(unconfirmed) == APPROVED  # an escalation nobody recorded is not a follow-up yet


def test_a_case_no_policy_covers_is_a_follow_up_for_a_person():
    case = new_case()
    append_case_event(case.case_id, "no_policy", "No applicable policy clause; needs manual handling", error="x")
    outcome = case_outcome(case.case_id)
    assert outcome.state == FOLLOW_UP and outcome.reason == "NO_POLICY"


def test_events_from_another_case_or_from_before_this_case_was_created_do_not_count():
    case = new_case()
    execute(new_case(order=recent_orders("C-001")[0]["order_id"], customer_id="C-001"))  # someone else's resolution
    assert state_of(case) == RECEIVED
    execute(case, "REPLACE")
    assert state_of(case) == RESOLVED
    append_case_event(case.case_id, "support_case_created", "a new run reusing the id", channel="WEB")  # stale history ends here
    assert state_of(case) == RECEIVED


def test_the_helper_writes_what_the_real_checkpoint_writes():
    """Guards the helper itself: a real approval of the demo case and the helper give the same event shapes."""
    real = new_case()
    run = propose_resolution(real.case_id, RuleBasedModelProvider())
    decide(real.case_id, DecisionRequest(action=CheckpointAction.APPROVE, proposal_fingerprint=proposal_fingerprint(run.proposal), reviewer="Jordan"))
    assert case_outcome(real.case_id).state == RESOLVED  # the real thing satisfies the rule
    real_tail = [e for e in read_trace_events() if e.event_type in ("human_decision", "mock_action", "actions_executed")]

    fake = new_case()
    mark = len(read_trace_events())
    execute(fake, "REPLACE")
    fake_tail = read_trace_events()[mark:]

    def shape(events):
        return [(e.event_type, sorted((e.details.get("payload") or e.details).keys())) for e in events if e.event_type in ("human_decision", "mock_action", "actions_executed")]

    ignore = {"case_id", "payload"}
    clean = lambda rows: [(t, [k for k in keys if k not in ignore]) for t, keys in rows]  # noqa: E731
    assert [t for t, _ in shape(real_tail)] == [t for t, _ in shape(fake_tail)]
    assert clean(shape(real_tail)) == clean(shape(fake_tail))


# --- What Cosmo says --------------------------------------------------------------------------------------------------


def submitted_call():
    session = store.new_session("C-002", customer_first_name("C-002"), recent_orders("C-002"))
    for said in ("the smart plug", "It never arrived and tracking says it was lost.", "yes"):
        list(run_turn(session, said, None))
    assert session.state == store.STATE_SUBMITTED
    return session


def run_on(session, decision, **kwargs):
    run_actions(session.case_id, session.order_id, session.customer_id, decision, **kwargs)


def test_cosmo_says_nothing_about_an_outcome_until_the_actions_are_confirmed():
    session = submitted_call()
    approve(session.case_id)  # a person approved; nothing has run yet
    assert check_outcome(session) is None
    lines = [e["text"] for e in speak_outcome(session) if e["type"] == "agent_sentence"]
    assert lines == [cfg.text("STILL_WAITING", "en")]  # still on hold, no promise made
    assert session.state == store.STATE_SUBMITTED and session.outcome is None


def test_a_failure_part_way_never_makes_cosmo_announce_a_refund():
    session = submitted_call()
    run_on(session, "REFUND", amount=45.0, stop_before_summary=True)
    assert check_outcome(session) is None
    run_on(session, "REFUND", amount=45.0, unrecorded=("issue_refund",))
    assert check_outcome(session) is None
    assert not any("refund" in e["text"].lower() for e in speak_outcome(session) if e["type"] == "agent_sentence")


def test_cosmo_announces_the_resolution_once_it_is_confirmed_and_not_before():
    session = submitted_call()
    run_on(session, "REFUND", amount=45.0, stop_before_summary=True)
    assert check_outcome(session) is None
    session2 = submitted_call()
    run_on(session2, "REFUND", amount=45.0, message="Your refund is on its way.")
    outcome = check_outcome(session2)
    assert outcome["status"] == "APPROVED" and "$45.00" in outcome["text"] and outcome["text"].endswith("full message is on your screen.")
    assert session2.state == store.STATE_CLOSED


def test_cosmo_gives_the_neutral_follow_up_line_for_an_escalation_a_person_made_and_for_a_rejection():
    escalated = submitted_call()
    run_on(escalated, "ESCALATE")
    assert check_outcome(escalated)["text"] == cfg.OUTCOME_ESCALATED
    rejected = submitted_call()
    run_on(rejected, "REPLACE", approved=False)
    assert check_outcome(rejected)["text"] == cfg.OUTCOME_REJECTED


def test_cosmo_stays_silent_for_a_case_no_policy_covers_because_no_person_has_acted():
    session = submitted_call()
    append_case_event(session.case_id, "no_policy", "No applicable policy clause; needs manual handling", error="x")
    assert check_outcome(session) is None
