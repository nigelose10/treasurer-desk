from desk.commands import is_treasurer, is_verdict_handoff, parse_command


def test_approve_reject_adjust_summary_ledger_and_why():
    assert parse_command("@bookkeeper approve C-007").kind == "approve"
    assert parse_command("approve C-7").claim_id == "C-7".upper() or parse_command("approve C-007").claim_id == "C-007"
    approved = parse_command('approve C-007 override="board said ok"')
    assert approved.kind == "approve"
    assert approved.claim_id == "C-007"
    assert approved.override == "board said ok"
    rejected = parse_command("reject C-007 too late")
    assert rejected.kind == "reject"
    assert rejected.reason == "too late"
    adjusted = parse_command("adjust C-007 amount=38.00")
    assert adjusted.kind == "adjust"
    assert adjusted.amount == "38.00"
    assert parse_command("adjust C-007 amount=1,234.50").amount == "1234.50"
    assert parse_command("please summary november").kind == "summary"
    assert parse_command("show the ledger").kind == "ledger"
    why = parse_command("why C-007")
    assert why.kind == "why"
    assert why.claim_id == "C-007"


def test_unknown_command():
    assert parse_command("hello there").kind == "unknown"


def test_a_verdict_that_mentions_approve_is_still_a_handoff():
    text = "C-001 PASS\nThe treasurer can `@bookkeeper approve C-001`."
    assert is_verdict_handoff(text)
    assert not is_verdict_handoff("approve C-001")


def test_treasurer_must_be_the_named_human():
    people = [
        {"name": "user", "type": "user"},
        {"name": "maya", "type": "user"},
        {"name": "user", "type": "agent"},
    ]
    allowed = {"user"}
    assert is_treasurer("user", "@switch-mattermost-abc-user:localhost", people, allowed)
    assert not is_treasurer("maya", "@switch-mattermost-abc-maya:localhost", people, allowed)
    assert not is_treasurer("user", "@switch-agent-afb9ccfb:localhost", people, allowed)
    assert not is_treasurer("stranger", "@switch-mattermost-x:localhost", people, allowed)
    assert not is_treasurer("user", "@switch-mattermost-abc-user:localhost", [], allowed)
