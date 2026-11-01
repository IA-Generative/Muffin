"""The policy of the guardrails as a whole (#516): in parallel and waited for, by stages, counted by `any` or `quorum`,
cut short by `first_block`, handled by `fail_open` / `fail_closed`, masked before the next stage, and never run when
there is nothing to run."""

import asyncio
import time

import pytest

from app.guardrails import runner
from app.guardrails.types import (
    CANCELLED,
    CLEAR,
    ERROR,
    FLAGGED,
    OUTCOME_BLOCK,
    OUTCOME_CONTINUE,
    OUTCOME_REDACTION,
    OUTCOME_WARNING,
    TIMEOUT,
    Policy,
    Spec,
    Verdict,
)
from app.models.guardrail import (
    Aggregation,
    Enforcement,
    GuardrailType,
    OnError,
    OnIncomplete,
    WaitStrategy,
)


def make(name, *, flag=False, delay=0.0, fail=False, enforcement=Enforcement.BLOCK, stage=1, **fields) -> Spec:
    """A guardrail that behaves as told: it waits `delay`, then flags, answers clear or fails."""
    return Spec(
        None,
        name,
        GuardrailType.RULES,
        {"flag": flag, "delay": delay, "fail": fail},
        enforcement,
        stage,
        **fields,
    )


@pytest.fixture
def calls(monkeypatch):
    """What the guardrails were asked, in order, and the text each one received."""
    seen: list[tuple[str, str]] = []

    async def fake(spec: Spec, text: str, user_id, run_id) -> Verdict:
        seen.append((spec.name, text))
        await asyncio.sleep(spec.config["delay"])
        if spec.config["fail"]:
            raise RuntimeError("down")
        return Verdict(FLAGGED, "cat", 1.0) if spec.config["flag"] else Verdict(CLEAR)

    monkeypatch.setattr(runner, "_check", fake)
    return seen


def statuses(decision) -> dict[str, str]:
    return {result.spec.name: result.verdict.status for result in decision.results}


def actions(decision) -> dict[str, str]:
    return {result.spec.name: result.action for result in decision.results}


# --- nothing to run ---


async def test_with_no_guardrail_nothing_runs_and_the_text_goes_on_as_it_is(calls):
    decision = await runner.evaluate("Bonjour", [], Policy())

    assert (decision.outcome, decision.text, decision.results, calls) == (OUTCOME_CONTINUE, "Bonjour", [], [])


# --- in parallel, and waited for ---


async def test_the_guardrails_of_a_stage_run_together_and_every_verdict_is_waited_for(calls):
    specs = [make("a", delay=0.3), make("b", delay=0.3, flag=True, enforcement=Enforcement.MONITOR)]

    started = time.monotonic()
    decision = await runner.evaluate("texte", specs, Policy(timeout_ms=5000))
    elapsed = time.monotonic() - started

    assert elapsed < 0.55  # about the slowest, not the sum
    assert statuses(decision) == {"a": CLEAR, "b": FLAGGED} and decision.outcome == OUTCOME_CONTINUE
    assert actions(decision)["b"] == "monitored"
    assert sorted(name for name, _ in calls) == ["a", "b"]


async def test_one_blocking_guardrail_that_flags_is_enough_to_stop_and_the_others_are_still_recorded(calls):
    specs = [
        make("fast", flag=True),
        make("slow", delay=0.2),
        make("watcher", flag=True, enforcement=Enforcement.MONITOR),
    ]

    decision = await runner.evaluate("texte", specs, Policy(timeout_ms=5000))

    assert decision.outcome == OUTCOME_BLOCK and decision.blocked
    assert statuses(decision) == {"fast": FLAGGED, "slow": CLEAR, "watcher": FLAGGED}
    assert actions(decision) == {"fast": "blocked", "slow": "none", "watcher": "monitored"}


# --- by stages ---


async def test_stage_two_does_not_start_when_stage_one_blocks(calls):
    specs = [make("free_rule", flag=True, stage=1), make("costly_model", stage=2)]

    decision = await runner.evaluate("texte", specs, Policy())

    assert decision.outcome == OUTCOME_BLOCK
    assert [name for name, _ in calls] == ["free_rule"]
    assert statuses(decision) == {"free_rule": FLAGGED}


async def test_stage_two_runs_when_stage_one_passed_and_receives_the_text_masked_by_stage_one(monkeypatch, calls):
    async def masking(spec, text, user_id, run_id):
        calls.append((spec.name, text))
        if spec.name == "masker":
            from app.guardrails.types import Span

            start = text.index("secret")
            return Verdict(FLAGGED, "pii", 1.0, spans=[Span(start, start + 6, "SECRET")])
        return Verdict(CLEAR)

    monkeypatch.setattr(runner, "_check", masking)
    specs = [make("masker", enforcement=Enforcement.REDACT, stage=1), make("judge", stage=2)]

    decision = await runner.evaluate("le secret est ici", specs, Policy())

    assert decision.outcome == OUTCOME_REDACTION and decision.text == "le [SECRET] est ici"
    assert calls == [("masker", "le secret est ici"), ("judge", "le [SECRET] est ici")]
    assert actions(decision)["masker"] == "redacted"


# --- aggregation ---


async def test_with_a_quorum_one_flag_of_three_is_not_enough_and_two_are(calls):
    policy = Policy(aggregation=Aggregation.QUORUM, quorum=2)

    one = await runner.evaluate("t", [make("a", flag=True), make("b"), make("c")], policy)
    two = await runner.evaluate("t", [make("a", flag=True), make("b", flag=True), make("c")], policy)

    assert one.outcome == OUTCOME_CONTINUE and actions(one)["a"] == "none"
    assert two.outcome == OUTCOME_BLOCK


async def test_a_quorum_larger_than_the_blocking_guardrails_asks_for_all_of_them(calls):
    policy = Policy(aggregation=Aggregation.QUORUM, quorum=5)

    decision = await runner.evaluate("t", [make("a", flag=True), make("b", flag=True)], policy)

    assert decision.outcome == OUTCOME_BLOCK


async def test_only_the_blocking_guardrails_count_for_the_quorum(calls):
    policy = Policy(aggregation=Aggregation.QUORUM, quorum=2)
    specs = [
        make("a", flag=True),
        make("b"),
        make("w", flag=True, enforcement=Enforcement.WARN),
        make("m", flag=True, enforcement=Enforcement.MONITOR),
    ]

    decision = await runner.evaluate("t", specs, policy)

    # One of the two blocking guardrails flags: the warning and the monitor that flag do not make the second.
    assert decision.outcome == OUTCOME_WARNING


# --- how long to wait ---


async def test_first_block_stops_the_others_as_soon_as_a_blocking_guardrail_flags(calls):
    specs = [make("fast", flag=True), make("slow", delay=5.0), make("also_slow", delay=5.0)]

    started = time.monotonic()
    decision = await runner.evaluate("t", specs, Policy(wait_strategy=WaitStrategy.FIRST_BLOCK, timeout_ms=10_000))
    elapsed = time.monotonic() - started

    assert elapsed < 1.0 and decision.outcome == OUTCOME_BLOCK
    assert statuses(decision) == {"fast": FLAGGED, "slow": CANCELLED, "also_slow": CANCELLED}
    assert actions(decision)["slow"] == "none"


async def test_with_first_block_and_nothing_flagging_every_verdict_is_still_waited_for(calls):
    specs = [make("a", delay=0.05), make("b", delay=0.15)]

    decision = await runner.evaluate("t", specs, Policy(wait_strategy=WaitStrategy.FIRST_BLOCK))

    assert statuses(decision) == {"a": CLEAR, "b": CLEAR}


async def test_the_whole_check_is_cut_at_the_global_time_and_what_did_not_answer_is_a_timeout(calls):
    specs = [make("fast"), make("slow", delay=5.0, timeout_ms=10_000)]

    started = time.monotonic()
    decision = await runner.evaluate("t", specs, Policy(timeout_ms=200))

    assert time.monotonic() - started < 1.0
    assert statuses(decision) == {"fast": CLEAR, "slow": TIMEOUT} and decision.outcome == OUTCOME_CONTINUE


async def test_each_guardrail_has_its_own_time(calls):
    decision = await runner.evaluate("t", [make("slow", delay=1.0, timeout_ms=100)], Policy(timeout_ms=10_000))

    assert statuses(decision) == {"slow": TIMEOUT}


async def test_the_time_left_for_a_later_stage_is_what_the_earlier_ones_did_not_use(calls):
    specs = [make("one", delay=0.25, stage=1), make("two", stage=2)]

    decision = await runner.evaluate("t", specs, Policy(timeout_ms=200))

    assert statuses(decision) == {"one": TIMEOUT, "two": TIMEOUT} and [name for name, _ in calls] == ["one"]


# --- when a guardrail fails ---


@pytest.mark.parametrize(
    ("on_error", "outcome", "action"),
    [(OnError.FAIL_OPEN, OUTCOME_CONTINUE, "ignored"), (OnError.FAIL_CLOSED, OUTCOME_BLOCK, "blocked")],
)
async def test_a_guardrail_that_fails_lets_through_or_blocks_as_it_was_told(calls, on_error, outcome, action):
    decision = await runner.evaluate("t", [make("service", fail=True, on_error=on_error)], Policy())

    assert statuses(decision) == {"service": ERROR} and decision.outcome == outcome
    assert actions(decision)["service"] == action


@pytest.mark.parametrize(
    ("on_error", "outcome"), [(OnError.FAIL_OPEN, OUTCOME_CONTINUE), (OnError.FAIL_CLOSED, OUTCOME_BLOCK)]
)
async def test_a_guardrail_that_is_too_slow_is_handled_like_one_that_fails(calls, on_error, outcome):
    decision = await runner.evaluate("t", [make("slow", delay=1.0, timeout_ms=50, on_error=on_error)], Policy())

    assert statuses(decision) == {"slow": TIMEOUT} and decision.outcome == outcome


async def test_a_critical_guardrail_that_cannot_answer_stops_the_request_even_when_it_fails_open(calls):
    decision = await runner.evaluate("t", [make("critical", fail=True, critical=True)], Policy())

    assert decision.outcome == OUTCOME_BLOCK


async def test_a_monitor_that_fails_closed_does_not_block(calls):
    decision = await runner.evaluate(
        "t", [make("m", fail=True, on_error=OnError.FAIL_CLOSED, enforcement=Enforcement.MONITOR)], Policy()
    )

    assert decision.outcome == OUTCOME_CONTINUE


async def test_what_a_failing_guardrail_raised_is_not_kept(calls, monkeypatch):
    logged = []
    monkeypatch.setattr(runner.logger, "warning", logged.append)
    secret = "SECRET-TEXT-OF-THE-PERSON"

    async def leaking(spec, text, user_id, run_id):
        raise RuntimeError(f"the service said: {text}")

    monkeypatch.setattr(runner, "_check", leaking)

    await runner.evaluate(secret, [make("service")], Policy())

    assert logged and all(secret not in message for message in logged)


# --- the verdicts that were asked for ---


async def test_with_too_few_verdicts_the_policy_decides_whether_the_request_goes_on(calls):
    specs = [make("a", fail=True), make("b", fail=True)]

    goes_on = await runner.evaluate("t", specs, Policy(min_verdicts=1, on_incomplete=OnIncomplete.CONTINUE))
    stops = await runner.evaluate("t", specs, Policy(min_verdicts=1, on_incomplete=OnIncomplete.BLOCK))
    enough = await runner.evaluate(
        "t", [make("a", fail=True), make("b")], Policy(min_verdicts=1, on_incomplete=OnIncomplete.BLOCK)
    )

    assert (goes_on.outcome, goes_on.incomplete) == (OUTCOME_CONTINUE, True)
    assert (stops.outcome, stops.incomplete) == (OUTCOME_BLOCK, True)
    assert (enough.outcome, enough.incomplete) == (OUTCOME_CONTINUE, False)


async def test_the_minimum_of_verdicts_is_asked_of_blocking_guardrails_only_and_never_more_than_there_are(calls):
    only_monitors = [make("m", enforcement=Enforcement.MONITOR, fail=True)]

    nothing_to_wait_for = await runner.evaluate(
        "t", only_monitors, Policy(min_verdicts=3, on_incomplete=OnIncomplete.BLOCK)
    )
    one_answered = await runner.evaluate("t", [make("a")], Policy(min_verdicts=3, on_incomplete=OnIncomplete.BLOCK))

    assert nothing_to_wait_for.outcome == OUTCOME_CONTINUE and one_answered.outcome == OUTCOME_CONTINUE


# --- the guardrails that do not block ---


async def test_a_warning_goes_on_with_its_notice_and_a_monitor_shows_nothing(calls):
    warn = make("w", flag=True, enforcement=Enforcement.WARN, refusal_message="Évitez les données personnelles.")
    monitor = make("m", flag=True, enforcement=Enforcement.MONITOR)

    warned = await runner.evaluate("t", [warn, monitor], Policy())
    silent = await runner.evaluate("t", [monitor], Policy())

    assert (warned.outcome, warned.message) == (OUTCOME_WARNING, "Évitez les données personnelles.")
    assert actions(warned) == {"w": "warned", "m": "monitored"}
    assert (silent.outcome, silent.message, silent.text) == (OUTCOME_CONTINUE, None, "t")
    assert actions(silent) == {"m": "monitored"}


async def test_a_redaction_that_found_nothing_to_mask_changes_nothing(calls):
    decision = await runner.evaluate("texte", [make("r", flag=True, enforcement=Enforcement.REDACT)], Policy())

    assert decision.outcome == OUTCOME_CONTINUE and decision.text == "texte" and actions(decision)["r"] == "none"


async def test_a_service_that_masks_by_itself_gives_the_text_that_goes_on(monkeypatch, calls):
    async def masks(spec, text, user_id, run_id):
        return Verdict(FLAGGED, "pii", 1.0, redacted_text="Bonjour <PERSONNE>")

    monkeypatch.setattr(runner, "_check", masks)

    decision = await runner.evaluate("Bonjour Jean", [make("svc", enforcement=Enforcement.REDACT)], Policy())

    assert decision.outcome == OUTCOME_REDACTION and decision.text == "Bonjour <PERSONNE>"


# --- what the person is told ---


async def test_a_refusal_says_the_words_of_the_guardrail_or_the_policys_and_never_the_rule(calls):
    own = make(
        "own",
        flag=True,
        refusal_message="Pas de numéro de sécurité sociale ici.",
        category_label="données personnelles",
    )
    plain = make("plain", flag=True)
    policy = Policy(default_refusal="Demande refusée.")

    with_own = await runner.evaluate("t", [own], policy)
    with_default = await runner.evaluate("t", [plain], policy)

    assert with_own.message == "Pas de numéro de sécurité sociale ici."
    assert with_default.message == "Demande refusée."
    assert "own" not in with_own.message and "plain" not in with_default.message


async def test_the_general_category_is_named_only_when_the_policy_allows_it(calls):
    spec = make("pii", flag=True, category_label="données personnelles")

    neutral = await runner.evaluate("t", [spec], Policy(default_refusal="Refusée.", show_category=False))
    named = await runner.evaluate("t", [spec], Policy(default_refusal="Refusée.", show_category=True))

    assert neutral.message == "Refusée." and named.message == "Refusée. (catégorie : données personnelles)"


async def test_a_blocked_request_keeps_its_original_text_for_the_caller_to_store_nowhere(calls):
    decision = await runner.evaluate("mon iban", [make("a", flag=True)], Policy())

    assert decision.text == "mon iban"  # the caller never sends it on: a block stops the run
