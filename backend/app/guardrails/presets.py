"""The guardrails that come with the application (#516): made once, **disabled**, in the mode that only watches, for an
administrator to enable, adjust or delete. A list of terms is left empty for the organisation to fill."""

from typing import Any

from app.guardrails.llm import DEFAULT_PROMPT
from app.models.guardrail import Enforcement, GuardrailType

PRESETS: list[dict[str, Any]] = [
    {
        "preset_key": "personal_data_fr",
        "name": "Données personnelles françaises",
        "description": "E-mail, téléphone, IBAN et numéro de sécurité sociale (NIR), contrôlés par leur clé.",
        "type": GuardrailType.RULES,
        "config": {"builtins": ["email", "phone_fr", "iban", "nir"], "category": "données personnelles"},
        "enforcement": Enforcement.MONITOR,
        "category_label": "données personnelles",
        "stage": 1,
    },
    {
        "preset_key": "secrets",
        "name": "Secrets et clés d'API",
        "description": "Clés d'API, jetons, clés privées et mots de passe collés dans une question.",
        "type": GuardrailType.RULES,
        "config": {"builtins": ["secret"], "category": "secrets"},
        "enforcement": Enforcement.MONITOR,
        "category_label": "secrets",
        "stage": 1,
    },
    {
        "preset_key": "max_length",
        "name": "Longueur maximale",
        "description": "Une demande plus longue que 8 000 caractères.",
        "type": GuardrailType.RULES,
        "config": {"max_chars": 8000, "category": "longueur"},
        "enforcement": Enforcement.MONITOR,
        "category_label": "longueur",
        "stage": 1,
    },
    {
        "preset_key": "forbidden_terms",
        "name": "Termes interdits",
        "description": "Termes que l'organisation ne veut pas voir dans une demande. La liste est vide : à remplir.",
        "type": GuardrailType.RULES,
        "config": {"terms": [], "category": "termes interdits"},
        "enforcement": Enforcement.MONITOR,
        "category_label": "termes interdits",
        "stage": 1,
    },
    {
        "preset_key": "prompt_injection",
        "name": "Injection de consignes",
        "description": "Un modèle juge si la demande tente de contourner les consignes de l'assistant (1 appel).",
        "type": GuardrailType.LLM,
        "config": {"prompt": DEFAULT_PROMPT, "categories": ["injection"], "threshold": 0.7},
        "enforcement": Enforcement.MONITOR,
        "category_label": "consignes",
        "stage": 2,
    },
]
