"""Tests for the Step Functions ASL definition shape."""

from __future__ import annotations

from oligos_agents.statemachine import build_definition

_ARNS = {
    "route": "arn:route",
    "retrieve": "arn:retrieve",
    "detect": "arn:detect",
    "draft": "arn:draft",
    "store_token": "arn:store_token",
    "execute_writes": "arn:execute_writes",
    "specialist": "arn:specialist",
}


def test_definition_has_expected_states():
    definition = build_definition(_ARNS)
    states = definition["States"]
    for name in (
        "Route",
        "IntentChoice",
        "Retrieve",
        "Detect",
        "Draft",
        "AwaitApproval",
        "ExecuteWrites",
        "Specialist",
        "Done",
        "NeedsReview",
        "Rejected",
        "Failed",
    ):
        assert name in states
    assert definition["StartAt"] == "Route"


def test_await_approval_uses_task_token_pattern():
    await_state = build_definition(_ARNS)["States"]["AwaitApproval"]
    assert await_state["Resource"] == "arn:aws:states:::lambda:invoke.waitForTaskToken"
    assert await_state["Parameters"]["Payload"]["taskToken.$"] == "$$.Task.Token"
    assert await_state["TimeoutSeconds"] == 604800


def test_tasks_have_retry_and_catch():
    route = build_definition(_ARNS)["States"]["Route"]
    assert route["Retry"]
    assert route["Catch"][0]["Next"] == "Failed"
