"""Prompts LLM dédiés aux fichiers tabulaires.

Contrairement au pipeline classique (map-reduce sur les pages de texte),
ici le LLM reçoit un contexte structuré et compact :
- le schéma (noms de colonnes + types) ;
- les stats descriptives (nb lignes, NULLs, cardinalité, min/max/moyenne) ;
- un échantillon de quelques lignes.

Pas de map-reduce : un fichier tabulaire tient en un seul prompt, même avec
des centaines de colonnes (le profil est compact par construction).

Ces prompts sont utilisés par ``_tabular_steps.generate_summary`` et
``_tabular_steps.generate_qa_pairs``, qui envoient le prompt via
``_shared._chat`` (même mécanisme que les documents classiques) et sauvent
le résultat via ``set_document_summary`` / ``create_qa_pair`` (même
persistance que les documents classiques).
"""

from __future__ import annotations

import json

from app.tabular.stats import TabularProfile


def _format_schema(profile: TabularProfile) -> str:
    """Schéma lisible : une ligne par colonne avec type, type sémantique et
    stats clés."""
    lines = []
    for col in profile.columns:
        parts = [f"- {col.name} ({col.type}, {col.semantic_type})"]
        parts.append(f"{col.null_count} nulls")
        parts.append(f"{col.distinct_count} distincts")
        if col.numeric_stats:
            ns = col.numeric_stats
            parts.append(f"min={ns['min']}, max={ns['max']}, moy={ns['mean']}")
        if col.date_stats:
            parts.append(f"plage: {col.date_stats['min']} → {col.date_stats['max']}")
        if col.text_stats:
            ts = col.text_stats
            parts.append(f"longueur: min={ts['min_length']}, max={ts['max_length']}, moy={ts['avg_length']:.0f}")
        elif col.top_values:
            top = ", ".join(f"{v['value']} ({v['count']})" for v in col.top_values[:3])
            parts.append(f"top: {top}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _format_sample_rows(profile: TabularProfile) -> str:
    """Échantillon de lignes en markdown table pour le LLM."""
    if not profile.sample_rows:
        return "(aucune ligne)"
    columns = list(profile.sample_rows[0].keys())
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    rows = []
    for row in profile.sample_rows:
        values = [str(row.get(col, "")) for col in columns]
        rows.append("| " + " | ".join(values) + " |")
    return "\n".join([header, separator, *rows])


def _format_classification(profile: TabularProfile) -> str:
    """Classification measures/dimensions/text_columns pour le LLM."""
    parts = []
    if profile.measures:
        parts.append(f"Measures: {', '.join(profile.measures)}")
    if profile.dimensions:
        parts.append(f"Dimensions: {', '.join(profile.dimensions)}")
    if profile.text_columns:
        parts.append(f"Colonnes texte: {', '.join(profile.text_columns)}")
    return "\n".join(parts) if parts else "(aucune classification)"


def build_summary_prompt(profile: TabularProfile, instructions: str = "") -> tuple[str, str]:
    """Construit le prompt (system, user) pour le résumé tabulaire.

    Retourne un tuple (system_prompt, user_content) compatible avec
    ``_shared._chat(model, system, user_content)``.
    """
    system = instructions + "\n\n" if instructions else ""
    system += (
        "Tu es un analyste de données. Résume le fichier tabulaire ci-dessous de façon concise "
        "et utile pour un utilisateur qui découvre ce jeu de données. "
        "Indique : le sujet général du fichier, le nombre de lignes et de colonnes, "
        "les colonnes principales et leur rôle (measure, dimension, date, texte), "
        "et toute observation notable "
        "(valeurs manquantes, distributions, anomalies, plages temporelles). "
        "Réponds en français, en quelques paragraphes maximum."
    )

    user_content = (
        f"Format du fichier : {profile.format}\n"
        f"Nombre de lignes : {profile.row_count}\n"
        f"Nombre de colonnes : {profile.column_count}\n\n"
        f"Classification des colonnes :\n{_format_classification(profile)}\n\n"
        f"Schéma et statistiques :\n{_format_schema(profile)}\n\n"
        f"Échantillon de lignes :\n{_format_sample_rows(profile)}\n"
    )

    return system.strip(), user_content


def build_qa_prompt(profile: TabularProfile, instructions: str = "", k: int = 3) -> tuple[str, str]:
    """Construit le prompt pour générer k paires QA ancrées dans les données.

    Les questions doivent pouvoir être répondues en interrogeant la table
    (ex. « Combien de lignes où colonne X = valeur Y ? »), et les réponses
    doivent être chiffrées et exactes - le LLM les déduit des stats fournies.
    """
    system = instructions + "\n\n" if instructions else ""
    system += (
        "Tu génères des paires question/réponse ancrées dans les données réelles du fichier tabulaire. "
        "Les questions doivent porter sur des comptages, des agrégations ou des valeurs spécifiques "
        "qui peuvent être déduites des statistiques fournies. "
        "Les réponses doivent être précises et chiffrées quand c'est possible. "
        f"Génère exactement {k} paires. "
        'Réponds uniquement avec un tableau JSON : [{"question": ..., "answer": ...}].'
    )

    user_content = (
        f"Format : {profile.format}, {profile.row_count} lignes, {profile.column_count} colonnes.\n\n"
        f"Classification :\n{_format_classification(profile)}\n\n"
        f"Schéma et statistiques :\n{_format_schema(profile)}\n\n"
        f"Échantillon de lignes :\n{_format_sample_rows(profile)}\n"
    )

    return system.strip(), user_content


def parse_qa_response(raw: str) -> list[dict[str, str]]:
    """Parse la réponse JSON du LLM en liste de paires QA.
    Lève ValueError si le format est invalide."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = cleaned.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        cleaned = "\n".join(lines).strip()

    pairs = json.loads(cleaned)
    if not isinstance(pairs, list):
        raise ValueError(f"Expected a JSON array of QA pairs, got: {type(pairs)!r}")

    result: list[dict[str, str]] = []
    for pair in pairs:
        if not isinstance(pair, dict) or "question" not in pair or "answer" not in pair:
            raise ValueError(f"Invalid QA pair: {pair!r}")
        result.append({"question": str(pair["question"]), "answer": str(pair["answer"])})
    return result
