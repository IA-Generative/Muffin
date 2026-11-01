"""Runs the guardrails on a request and decides what becomes of it (#516).

The guardrails of a stage start together and their verdicts are waited for, within the time of the guardrail and of the
whole; the guardrails of stage 2 start only if the request passed stage 1, so that the free checks (`rules`) go before
the costly ones (`llm`, `http`). What a stage settles follows the policy: one blocking guardrail that flags is enough
(`any`), or at least `quorum` of them; the others are waited for (`wait_all`, to record everything) or cancelled as soon
as it is settled (`first_block`). A guardrail that fails or is too slow is handled by its own `on_error`, and the policy
says what to do when too few of the blocking ones answered (`on_incomplete`).

The text that goes on is masked by the guardrails that redact: the models never see what was masked. Nothing here keeps
the text: only verdicts, categories, scores and times come out."""

import asyncio
import time

from loguru import logger

from app.guardrails import http as http_guardrail
from app.guardrails import llm as llm_guardrail
from app.guardrails import rules as rules_guardrail
from app.guardrails.types import (
    CANCELLED,
    CLEAR,
    ERROR,
    FLAGGED,
    OUTCOME_BLOCK,
    OUTCOME_CONTINUE,
    OUTCOME_REDACTION,
    OUTCOME_WARNING,
    REDACTION_NOTICE,
    TIMEOUT,
    WARNING_NOTICE,
    Decision,
    Policy,
    Result,
    Spec,
    Verdict,
)
from app.models.guardrail import Aggregation, Enforcement, GuardrailType, OnError, OnIncomplete, WaitStrategy


async def run_one(
    spec: Spec, text: str, timeout: float, *, user_id: str | None = None, run_id: str | None = None
) -> Verdict:
    """One guardrail, under its time. Never raises: a failure is an `error` verdict, a delay a `timeout`."""
    started = time.monotonic()
    try:
        verdict = await asyncio.wait_for(_check(spec, text, user_id, run_id), timeout=max(timeout, 0.001))
    except TimeoutError:
        verdict = Verdict(TIMEOUT)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        # The kind of failure only: what a service or a model answered may repeat the text.
        logger.warning(f"The guardrail {spec.name} failed: {type(error).__name__}")
        verdict = Verdict(ERROR)
    verdict.latency_ms = int((time.monotonic() - started) * 1000)
    return verdict


async def _check(spec: Spec, text: str, user_id: str | None, run_id: str | None) -> Verdict:
    if spec.type == GuardrailType.RULES:
        return await asyncio.to_thread(rules_guardrail.check, spec.config, text)
    if spec.type == GuardrailType.LLM:
        return await llm_guardrail.check(spec, text, user_id=user_id, run_id=run_id)
    return await http_guardrail.check(spec, text)


def _handle_failure(spec: Spec, verdict: Verdict) -> Result:
    """What a guardrail that did not answer counts as: `fail_closed` (or critical) flags, `fail_open` lets it go."""
    if verdict.status in (ERROR, TIMEOUT):
        closed = spec.on_error == OnError.FAIL_CLOSED or spec.critical
        return Result(spec, verdict, flagged=closed, action="none" if closed else "ignored")
    return Result(spec, verdict, flagged=verdict.status == FLAGGED)


def _settled(results: list[Result], blocking_total: int, policy: Policy) -> bool:
    """Whether the blocking guardrails that answered already decide the stage: enough of them flag."""
    flagged = sum(1 for result in results if result.spec.blocking and result.flagged)
    needed = 1 if policy.aggregation == Aggregation.ANY else min(max(policy.quorum, 1), max(blocking_total, 1))
    return flagged >= needed


async def _run_stage(
    specs: list[Spec], text: str, deadline: float, policy: Policy, *, user_id: str | None, run_id: str | None
) -> list[Result]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return [_handle_failure(spec, Verdict(TIMEOUT)) for spec in specs]
    blocking_total = sum(1 for spec in specs if spec.blocking)
    tasks = {
        asyncio.create_task(
            run_one(spec, text, min(spec.timeout_ms / 1000, remaining), user_id=user_id, run_id=run_id)
        ): index
        for index, spec in enumerate(specs)
    }
    # By the place of the guardrail in the stage: a Spec holds a dict and cannot be a key.
    done_results: dict[int, Result] = {}
    pending = set(tasks)
    try:
        while pending:
            done, pending = await asyncio.wait(
                pending, timeout=max(deadline - time.monotonic(), 0.001), return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                break  # the whole check is out of time
            for task in done:
                done_results[tasks[task]] = _handle_failure(specs[tasks[task]], task.result())
            if (
                policy.wait_strategy == WaitStrategy.FIRST_BLOCK
                and pending
                and _settled(list(done_results.values()), blocking_total, policy)
            ):
                break
    finally:
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
    stopped = policy.wait_strategy == WaitStrategy.FIRST_BLOCK and _settled(
        list(done_results.values()), blocking_total, policy
    )
    for task in pending:
        spec = specs[tasks[task]]
        done_results[tasks[task]] = (
            Result(spec, Verdict(CANCELLED)) if stopped else _handle_failure(spec, Verdict(TIMEOUT))
        )
    return [done_results[index] for index in range(len(specs))]


def _apply_redactions(text: str, results: list[Result]) -> tuple[str, bool]:
    """The text with what the guardrails that redact found masked. A service that masks by itself gives its own text,
    taken only when no rule has marked parts of the same text."""
    spans = [
        span
        for result in results
        if result.flagged and result.spec.enforcement == Enforcement.REDACT
        for span in result.verdict.spans
    ]
    if spans:
        return rules_guardrail.redact(text, spans), True
    for result in results:
        if result.flagged and result.spec.enforcement == Enforcement.REDACT and result.verdict.redacted_text:
            return result.verdict.redacted_text, True
    return text, False


def _message_of(blocking: list[Result], policy: Policy) -> str:
    """What a refusal says: the words of the guardrail that stopped the request, else the policy's - and the general
    category when the policy allows naming it. Never the rule."""
    first = blocking[0].spec if blocking else None
    message = (first.refusal_message if first else None) or policy.default_refusal
    if policy.show_category and first and first.category_label:
        message = f"{message} (catégorie : {first.category_label})"
    return message


async def evaluate(
    text: str, specs: list[Spec], policy: Policy, *, user_id: str | None = None, run_id: str | None = None
) -> Decision:
    """What becomes of a request: `continue`, `continue_with_redaction`, `continue_with_warning` or `block`, with the
    text that goes on and what was seen. With no guardrail, nothing is run and the text goes on as it is."""
    if not specs:
        return Decision(OUTCOME_CONTINUE, text, [])
    deadline = time.monotonic() + policy.timeout_ms / 1000
    current = text
    results: list[Result] = []
    redacted = False
    blocked_by: list[Result] = []
    for stage in sorted({spec.stage for spec in specs}):
        stage_results = await _run_stage(
            [spec for spec in specs if spec.stage == stage], current, deadline, policy, user_id=user_id, run_id=run_id
        )
        results.extend(stage_results)
        blocking_total = sum(1 for spec in specs if spec.stage == stage and spec.blocking)
        if _settled(stage_results, blocking_total, policy):
            blocked_by = [result for result in stage_results if result.spec.blocking and result.flagged]
            break
        current, changed = _apply_redactions(current, stage_results)
        redacted = redacted or changed

    blocking_specs = [spec for spec in specs if spec.blocking]
    answered = sum(1 for result in results if result.spec.blocking and result.verdict.answered)
    incomplete = bool(blocking_specs) and answered < min(policy.min_verdicts, len(blocking_specs))
    blocked = bool(blocked_by) or (incomplete and policy.on_incomplete == OnIncomplete.BLOCK)
    _name_actions(results, blocked_by, blocked)

    if blocked:
        return Decision(OUTCOME_BLOCK, text, results, _message_of(blocked_by, policy), incomplete)
    warned = [result for result in results if result.action == "warned"]
    if redacted:
        return Decision(OUTCOME_REDACTION, current, results, REDACTION_NOTICE, incomplete)
    if warned:
        return Decision(OUTCOME_WARNING, current, results, warned[0].spec.refusal_message or WARNING_NOTICE, incomplete)
    return Decision(OUTCOME_CONTINUE, current, results, None, incomplete)


def _name_actions(results: list[Result], blocked_by: list[Result], blocked: bool) -> None:
    """What each flagging guardrail led to - recorded with its verdict, so that the administrator sees what each did."""
    stopping = {id(result) for result in blocked_by}
    for result in results:
        if result.verdict.status == CANCELLED or not result.flagged:
            continue
        enforcement = result.spec.enforcement
        if enforcement == Enforcement.BLOCK:
            result.action = "blocked" if id(result) in stopping else "none"
        elif enforcement == Enforcement.WARN:
            result.action = "warned"
        elif enforcement == Enforcement.REDACT:
            result.action = "redacted" if result.verdict.spans or result.verdict.redacted_text else "none"
        else:
            result.action = "monitored"
    # A verdict that is clear did nothing.
    for result in results:
        if result.verdict.status == CLEAR:
            result.action = "none"
