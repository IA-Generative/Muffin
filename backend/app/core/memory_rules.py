"""What may be remembered of a person, and how it is named (#282). No model, no network: it runs on every write."""

import re
import unicodedata

from app.config.memory import MemorySettings

_settings = MemorySettings()

# The special categories of the GDPR (art. 9) and what comes close: health, political and religious opinions, origin,
# sexual orientation, trade union membership, genetic and biometric data, convictions. Never remembered - not even when
# the person asks for it. A list of words, not a judgement of a text: it errs on the safe side (a profession that deals
# with these subjects is refused too, and the person may word it otherwise), and the guardrails (#516) come on top.
_SENSITIVE = re.compile(
    r"\b("
    # health
    r"diabet\w*|cancer\w*|tumeur\w*|depress\w*|bipolaire|schizophren\w*|anorexi\w*|boulimi\w*|autis\w*|"
    r"handicap\w*|vih|sida|seropositi\w*|epilep\w*|alzheimer|parkinson|sclerose|chimiotherap\w*|"
    r"enceinte|grossesse|fausse couche|avortement|maladie\w*|malade|pathologie\w*|traitement medical|"
    r"mon etat de sante|ma sante|mes problemes de sante|arret maladie|psychiatr\w*|"
    # opinions
    r"mon vote|je vote|j'ai vote|electeur|mes opinions politiques|mon parti|ma religion|ma foi|mes convictions|"
    r"musulman\w*|juif|juive|juifs|chretien\w*|catholique\w*|protestant\w*|orthodoxe\w*|bouddhiste\w*|hindou\w*|"
    r"sikh\w*|athee\w*|agnostique\w*|islam\w*|"
    # origin
    r"mon origine|mes origines|origine ethnique|ethnie|couleur de peau|"
    # orientation, genetics, union, convictions
    r"homosexuel\w*|lesbienne\w*|gay|bisexuel\w*|transgenre\w*|orientation sexuelle|"
    r"syndique\w*|appartenance syndicale|mon syndicat|"
    r"adn|genetique|empreinte\w* digitale\w*|casier judiciaire|condamnation\w*|condamne"
    r")\b"
)


class MemoryRefusedError(ValueError):
    """Why a thing is not kept: `code` is for the program, the message for the person."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def fold(text: str) -> str:
    """Lower case, no accents, single spaces: the form two writings of one thing share."""
    text = unicodedata.normalize("NFKD", text.casefold().replace("’", "'"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def clean(value: str) -> str:
    """The sentence as it is kept: one line, no control characters."""
    return re.sub(r"\s+", " ", "".join(c if c.isprintable() or c.isspace() else " " for c in value)).strip()


def key_of(value: str) -> str:
    """The name of what is remembered, from its words: the same sentence written twice is one item, not two."""
    return re.sub(r"[^a-z0-9]+", "-", fold(value)).strip("-")[:80] or "item"


def check(value: str) -> str:
    """The sentence to keep, or why it is refused."""
    value = clean(value)
    if not value:
        raise MemoryRefusedError("vide", "Il n'y a rien à retenir.")
    if len(value) > _settings.MEMORY_VALUE_MAX_CHARS:
        raise MemoryRefusedError(
            "trop_long", f"C'est trop long : {_settings.MEMORY_VALUE_MAX_CHARS} caractères au plus."
        )
    if _SENSITIVE.search(fold(value)):
        raise MemoryRefusedError(
            "sensible",
            "Je ne retiens rien sur la santé, les opinions, l'origine, la vie privée ou ce qui s'en approche : "
            "ce n'est pas conservé, même sur demande.",
        )
    return value
