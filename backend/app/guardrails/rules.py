"""The guardrails of type `rules` (#516): code, no model. Patterns, lists of terms, a length - and a few detectors that
come with the application for what is found in French requests (e-mail, telephone, IBAN, NIR) and for secrets.

Configuration of a guardrail of this type:

    {
      "builtins": ["email", "phone_fr", "iban", "nir", "secret"],
      "patterns": [{"name": "dossier", "regex": "DOS-\\d{6}", "label": "DOSSIER"}],
      "terms": ["mot interdit"],
      "max_chars": 8000,
      "category": "données personnelles"
    }

A pattern is written by an administrator and run on every request of everyone: its length and number are bounded, it is
compiled when it is saved (a pattern that does not compile is refused), and a check that takes too long is cut by the
timeout of the guardrail. The detectors validate what they find (the key of an IBAN, of a NIR) so that a number that
only looks like one is not flagged."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from app.config import GuardrailSettings
from app.guardrails.types import CLEAR, FLAGGED, Span, Verdict

# Module attribute so that tests change it with monkeypatch.setattr.
_settings = GuardrailSettings()

# What the rules read at most: a longer text is only looked at up to there, and a rule on the length sees the real one.
RULES_TEXT_LIMIT = 200_000


class InvalidRulesError(ValueError):
    """The configuration of a guardrail of type `rules` is wrong: the message says what, for the administrator."""


_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_FR = re.compile(r"(?<![\d+])(?:\+33|0033|0)[\s.\-]?[1-9](?:[\s.\-]?\d{2}){4}(?!\d)")
_IBAN = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2}\d{2}(?:[ \-]?[A-Z0-9]{4}){2,7}(?:[ \-]?[A-Z0-9]{1,3})?(?![A-Za-z0-9])")
_NIR = re.compile(
    r"(?<!\d)[12][ .]?\d{2}[ .]?(?:0[1-9]|1[0-2]|[2-9]\d)[ .]?(?:\d{2}|2[AB])[ .]?\d{3}[ .]?\d{3}[ .]?\d{2}(?!\d)"
)
_SECRETS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY(?: BLOCK)?-----"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
    re.compile(r"(?i)\b(?:api[_\-]?key|secret|token|password|mot de passe|mdp)\s*[:=]\s*\S{8,}"),
]


def _iban_is_valid(text: str) -> bool:
    """The key of an IBAN (ISO 7064, mod 97): the letters are numbers (A=10...), the first four characters go last."""
    compact = re.sub(r"[ \-]", "", text).upper()
    if not 15 <= len(compact) <= 34:
        return False
    moved = compact[4:] + compact[:4]
    digits = "".join(str(int(char, 36)) for char in moved)
    return int(digits) % 97 == 1


def _nir_is_valid(text: str) -> bool:
    """The key of a French social security number: 97 minus the first 13 digits modulo 97 (Corsica: 2A is 19, 2B 18)."""
    compact = re.sub(r"[ .]", "", text).upper()
    if len(compact) != 15:
        return False
    body, key = compact[:13], compact[13:]
    body = body.replace("2A", "19").replace("2B", "18")
    if not (body.isdigit() and key.isdigit()):
        return False
    return 97 - int(body) % 97 == int(key)


@dataclass(frozen=True)
class _Detector:
    label: str
    patterns: tuple[re.Pattern, ...]
    validate: object = None  # a function of the matched text, or None


_DETECTORS: dict[str, _Detector] = {
    "email": _Detector("EMAIL", (_EMAIL,)),
    "phone_fr": _Detector("TELEPHONE", (_PHONE_FR,)),
    "iban": _Detector("IBAN", (_IBAN,), _iban_is_valid),
    "nir": _Detector("NIR", (_NIR,), _nir_is_valid),
    "secret": _Detector("SECRET", tuple(_SECRETS)),
}

BUILTINS = tuple(_DETECTORS)


@dataclass(frozen=True)
class Compiled:
    detectors: tuple[_Detector, ...]
    patterns: tuple[tuple[str, re.Pattern], ...]
    terms: re.Pattern | None
    max_chars: int | None
    category: str | None


def _compile_pattern(regex: str) -> re.Pattern:
    if not isinstance(regex, str) or not regex:
        raise InvalidRulesError("Un motif est vide.")
    if len(regex) > _settings.GUARDRAILS_PATTERN_MAX_CHARS:
        raise InvalidRulesError(f"Un motif dépasse {_settings.GUARDRAILS_PATTERN_MAX_CHARS} caractères.")
    try:
        compiled = re.compile(regex)
    except re.error as error:
        raise InvalidRulesError(f"Motif invalide : {error}.") from error
    if compiled.match(""):
        raise InvalidRulesError("Un motif ne doit pas accepter le texte vide.")
    return compiled


def compile_config(config: dict) -> Compiled:
    """The configuration, checked and compiled. Raises InvalidRulesError for what an administrator must fix."""
    builtins = config.get("builtins") or []
    unknown = [name for name in builtins if name not in _DETECTORS]
    if unknown:
        raise InvalidRulesError(f"Détecteur inconnu : {', '.join(map(str, unknown))}.")
    raw_patterns = config.get("patterns") or []
    if len(raw_patterns) > _settings.GUARDRAILS_PATTERNS_MAX:
        raise InvalidRulesError(f"Au plus {_settings.GUARDRAILS_PATTERNS_MAX} motifs.")
    patterns = []
    for item in raw_patterns:
        if not isinstance(item, dict):
            raise InvalidRulesError("Un motif est un objet {name, regex, label}.")
        label = str(item.get("label") or item.get("name") or "MOTIF").upper()[:24]
        patterns.append((label, _compile_pattern(item.get("regex"))))
    terms = [str(term).strip() for term in (config.get("terms") or []) if str(term).strip()]
    if len(terms) > _settings.GUARDRAILS_TERMS_MAX:
        raise InvalidRulesError(f"Au plus {_settings.GUARDRAILS_TERMS_MAX} termes.")
    terms_pattern = None
    if terms:
        alternatives = "|".join(re.escape(term) for term in sorted(set(terms), key=len, reverse=True))
        terms_pattern = re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)
    max_chars = config.get("max_chars")
    if max_chars is not None and (not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1):
        raise InvalidRulesError("La longueur maximale est un nombre entier positif.")
    category = config.get("category")
    return Compiled(
        detectors=tuple(_DETECTORS[name] for name in builtins),
        patterns=tuple(patterns),
        terms=terms_pattern,
        max_chars=max_chars,
        category=str(category)[:64] if category else None,
    )


@lru_cache(maxsize=256)
def _cached(key: str) -> Compiled:
    return compile_config(json.loads(key))


def compiled_for(config: dict) -> Compiled:
    """`compile_config`, remembered: the same configuration is run on every request."""
    return _cached(json.dumps(config, sort_keys=True, ensure_ascii=False))


def check(config: dict, text: str) -> Verdict:
    """The verdict of a guardrail of type `rules` on a text: flagged when a detector, a pattern, a term or the length
    says so, with the parts to mask. Synchronous and CPU-bound: the runner puts it in a thread, under the timeout."""
    compiled = compiled_for(config)
    length = len(text)
    text = text[:RULES_TEXT_LIMIT]
    spans: list[Span] = []
    labels: list[str] = []
    for detector in compiled.detectors:
        for pattern in detector.patterns:
            for match in pattern.finditer(text):
                if detector.validate is None or detector.validate(match.group()):
                    spans.append(Span(match.start(), match.end(), detector.label))
                    labels.append(detector.label)
    for label, pattern in compiled.patterns:
        for match in pattern.finditer(text):
            spans.append(Span(match.start(), match.end(), label))
            labels.append(label)
    if compiled.terms is not None:
        for match in compiled.terms.finditer(text):
            spans.append(Span(match.start(), match.end(), "TERME"))
            labels.append("TERME")
    too_long = compiled.max_chars is not None and length > compiled.max_chars
    if too_long:
        labels.append("LONGUEUR")
    if not spans and not too_long:
        return Verdict(CLEAR)
    category = compiled.category or labels[0].lower()
    return Verdict(FLAGGED, category=category, score=1.0, spans=_merged(spans))


def _merged(spans: list[Span]) -> list[Span]:
    """Overlapping parts become one, so that a text is masked once: the first marker is kept."""
    merged: list[Span] = []
    for span in sorted(spans, key=lambda item: (item.start, -item.end)):
        if merged and span.start < merged[-1].end:
            if span.end > merged[-1].end:
                merged[-1] = Span(merged[-1].start, span.end, merged[-1].label)
            continue
        merged.append(span)
    return merged


def redact(text: str, spans: list[Span]) -> str:
    """The text with each part replaced by its marker: `[EMAIL]`, `[IBAN]`... Not reversible: what was there is gone."""
    out: list[str] = []
    position = 0
    for span in _merged(list(spans)):
        out.append(text[position : span.start])
        out.append(f"[{span.label}]")
        position = span.end
    out.append(text[position:])
    return "".join(out)
