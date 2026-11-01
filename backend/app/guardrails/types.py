import uuid
from dataclasses import dataclass, field

from app.models.guardrail import Aggregation, Enforcement, GuardrailType, OnError, OnIncomplete, WaitStrategy

CLEAR = "clear"
FLAGGED = "flagged"
ERROR = "error"
TIMEOUT = "timeout"
CANCELLED = "cancelled"

OUTCOME_CONTINUE = "continue"
OUTCOME_REDACTION = "continue_with_redaction"
OUTCOME_WARNING = "continue_with_warning"
OUTCOME_BLOCK = "block"

WARNING_NOTICE = "Attention : votre demande contient peut-être des éléments qu'il vaut mieux ne pas partager."
REDACTION_NOTICE = "Des éléments sensibles ont été masqués avant l'envoi au modèle."


@dataclass(frozen=True)
class Span:
    """A part of the text a rule found, to be masked: [start, end) and the marker that takes its place."""

    start: int
    end: int
    label: str


@dataclass(frozen=True)
class Spec:
    """A guardrail as the engine runs it: what the database holds, without the database. The key of a service is only
    here for the time of the check, and never shown."""

    id: uuid.UUID | None
    name: str
    type: GuardrailType
    config: dict
    enforcement: Enforcement = Enforcement.MONITOR
    stage: int = 1
    timeout_ms: int = 2000
    on_error: OnError = OnError.FAIL_OPEN
    critical: bool = False
    version: int = 1
    refusal_message: str | None = None
    category_label: str | None = None
    secret: str | None = field(default=None, repr=False)

    @property
    def blocking(self) -> bool:
        return self.enforcement == Enforcement.BLOCK


@dataclass(frozen=True)
class Policy:
    aggregation: Aggregation = Aggregation.ANY
    quorum: int = 2
    wait_strategy: WaitStrategy = WaitStrategy.WAIT_ALL
    timeout_ms: int = 2000
    on_incomplete: OnIncomplete = OnIncomplete.CONTINUE
    min_verdicts: int = 0
    show_category: bool = False
    default_refusal: str = (
        "Votre demande ne peut pas être traitée : elle ne respecte pas la politique d'usage de cette application."
    )


@dataclass
class Verdict:
    """What one guardrail said. `redacted_text` is only for a service that masks by itself (type `http`)."""

    status: str
    category: str | None = None
    score: float | None = None
    spans: list[Span] = field(default_factory=list)
    redacted_text: str | None = None
    latency_ms: int = 0

    @property
    def answered(self) -> bool:
        return self.status in (CLEAR, FLAGGED)


@dataclass
class Result:
    spec: Spec
    verdict: Verdict
    # Whether the guardrail counts as flagging once its failure is handled (`on_error`, `critical`).
    flagged: bool = False
    # `blocked`, `redacted`, `warned`, `monitored`, `ignored`, `none`.
    action: str = "none"


@dataclass
class Decision:
    outcome: str
    # What goes on to the models: the text, masked when it has to be.
    text: str
    results: list[Result]
    # What the person is told: the refusal of a block, or the notice of a warning or a masking.
    message: str | None = None
    # Whether the verdicts the policy asked for did not all come.
    incomplete: bool = False

    @property
    def blocked(self) -> bool:
        return self.outcome == OUTCOME_BLOCK
