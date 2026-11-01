"""The guardrails of type `rules` (#516): what they find, what they do not take for a find, how they mask, and a
configuration that is refused when it cannot be run safely."""

import pytest

from app.guardrails import rules
from app.guardrails.rules import InvalidRulesError, check, compile_config, redact
from app.guardrails.types import CLEAR, FLAGGED

VALID_IBAN = "FR76 3000 6000 0112 3456 7890 189"
VALID_NIR = "2 84 12 76 451 089 93"


def flagged(config: dict, text: str):
    return check(config, text)


@pytest.mark.parametrize(
    ("builtin", "text", "label"),
    [
        ("email", "Écrivez à jean.dupont@example.fr demain", "EMAIL"),
        ("phone_fr", "Appelez le 06 12 34 56 78 svp", "TELEPHONE"),
        ("phone_fr", "ou le +33 1 23 45 67 89", "TELEPHONE"),
        ("phone_fr", "ou le 0123456789", "TELEPHONE"),
        ("iban", f"Mon IBAN est {VALID_IBAN}.", "IBAN"),
        ("nir", f"Mon numéro : {VALID_NIR}", "NIR"),
        ("secret", "la clé sk-" + "a1b2c3d4e5f6g7h8i9j0k1", "SECRET"),
        ("secret", "AKIA" + "ABCDEFGHIJKLMNOP est la clé", "SECRET"),
        ("secret", "password = hunter2hunter2", "SECRET"),
        ("secret", "-----BEGIN RSA PRIVATE KEY-----", "SECRET"),
    ],
)
def test_the_detectors_find_what_they_are_made_for(builtin, text, label):
    verdict = flagged({"builtins": [builtin]}, text)

    assert verdict.status == FLAGGED and [span.label for span in verdict.spans] == [label]


@pytest.mark.parametrize(
    ("builtin", "text"),
    [
        ("iban", "FR76 3000 6000 0112 3456 7890 180"),  # the key is wrong
        ("nir", "2 84 12 76 451 089 47"),  # the key is wrong
        ("nir", "1234567890123"),
        ("phone_fr", "Le dossier 123456789012 est prêt"),
        ("email", "Rendez-vous à 14h, arobase @ non"),
        ("secret", "Le mot de passe doit faire huit caractères."),
    ],
)
def test_what_only_looks_like_one_is_not_a_find(builtin, text):
    assert check({"builtins": [builtin]}, text).status == CLEAR


def test_the_key_of_the_iban_and_of_the_nir_is_checked_so_that_a_number_is_not_taken_for_one():
    assert rules._iban_is_valid(VALID_IBAN) and not rules._iban_is_valid("FR76 3000 6000 0112 3456 7890 188")
    assert rules._nir_is_valid(VALID_NIR) and not rules._nir_is_valid("2 84 12 76 451 089 00")


def test_a_nir_from_corsica_is_read_with_2a_and_2b():
    # 2A is 19 and 2B is 18 in the computation of the key.
    body = "185052A001001"
    key = 97 - int(body.replace("2A", "19")) % 97
    assert rules._nir_is_valid(f"{body}{key:02d}")


def test_a_pattern_a_term_and_a_length_of_the_administrator_flag_with_their_own_marker():
    config = {
        "patterns": [{"name": "dossier", "regex": r"DOS-\d{6}", "label": "dossier"}],
        "terms": ["Projet Aurore", "confidentiel"],
        "max_chars": 50,
    }

    by_pattern = check(config, "voir DOS-123456")
    by_term = check(config, "Ceci est CONFIDENTIEL.")
    by_length = check(config, "x" * 60)
    inside_a_word = check(config, "inconfidentielle")

    assert [s.label for s in by_pattern.spans] == ["DOSSIER"] and [s.label for s in by_term.spans] == ["TERME"]
    assert by_length.status == FLAGGED and by_length.category == "longueur" and by_length.spans == []
    assert inside_a_word.status == CLEAR


def test_a_guardrail_with_nothing_to_look_for_never_flags():
    assert check({"terms": []}, "n'importe quoi").status == CLEAR
    assert check({}, "n'importe quoi").status == CLEAR


def test_the_category_is_the_one_configured_or_the_kind_of_the_first_find():
    assert (
        check({"builtins": ["iban"], "category": "données personnelles"}, VALID_IBAN).category == "données personnelles"
    )
    assert check({"builtins": ["iban"]}, VALID_IBAN).category == "iban"


def test_masking_replaces_each_find_with_its_marker_and_what_was_there_is_gone():
    text = f"Écrire à a@b.fr ou appeler 06 12 34 56 78, IBAN {VALID_IBAN}."
    verdict = check({"builtins": ["email", "phone_fr", "iban"]}, text)

    masked = redact(text, verdict.spans)

    assert masked == "Écrire à [EMAIL] ou appeler [TELEPHONE], IBAN [IBAN]."
    assert "a@b.fr" not in masked and "06 12" not in masked and "FR76" not in masked


def test_overlapping_finds_are_masked_once():
    text = "clé sk-abcdefghijklmnopqrstuvwx fin"
    verdict = check({"builtins": ["secret"], "patterns": [{"name": "cle", "regex": r"sk-\w+"}]}, text)

    assert redact(text, verdict.spans) == "clé [SECRET] fin"


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"builtins": ["nope"]}, "inconnu"),
        ({"patterns": [{"name": "x", "regex": "("}]}, "invalide"),
        ({"patterns": [{"name": "x", "regex": ""}]}, "vide"),
        ({"patterns": [{"name": "x", "regex": "a*"}]}, "texte vide"),
        ({"patterns": [{"name": "x", "regex": "a" * 501}]}, "500"),
        ({"patterns": "not a list of objects".split()}, "objet"),
        ({"max_chars": 0}, "positif"),
        ({"max_chars": True}, "positif"),
    ],
)
def test_a_configuration_that_cannot_be_run_safely_is_refused_with_a_reason(config, message):
    with pytest.raises(InvalidRulesError, match=message):
        compile_config(config)


def test_the_number_of_patterns_and_of_terms_is_bounded(monkeypatch):
    monkeypatch.setattr(rules._settings, "GUARDRAILS_PATTERNS_MAX", 2)
    monkeypatch.setattr(rules._settings, "GUARDRAILS_TERMS_MAX", 3)

    with pytest.raises(InvalidRulesError, match="motifs"):
        compile_config({"patterns": [{"regex": "a+"}, {"regex": "b+"}, {"regex": "c+"}]})
    with pytest.raises(InvalidRulesError, match="termes"):
        compile_config({"terms": ["a", "b", "c", "d"]})


def test_a_very_long_text_is_only_read_up_to_a_limit_but_its_length_is_the_real_one(monkeypatch):
    monkeypatch.setattr(rules, "RULES_TEXT_LIMIT", 100)
    text = "x" * 100 + " a@b.fr " + "y" * 500

    assert check({"builtins": ["email"]}, text).status == CLEAR  # the address is past the limit
    assert check({"max_chars": 300}, text).status == FLAGGED  # the length is not
