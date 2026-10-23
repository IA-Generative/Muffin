"""Tâche d'extraction d'entités et de relations nommées.

Parcourt une fenêtre de pages et demande au LLM d'extraire les entités
(personne, organisation, lieu, date, autre) et les relations entre elles.
Les entités sont upsertées (déduplication par nom), les relations lient
les entités résolues.
"""

from loguru import logger

from app.celery_app import celery_app
from app.entity_mentions import find_mentions
from app.tasks import _shared
from app.tasks.qa import evidence_position, locate_evidence


@celery_app.task(name="app.tasks.extract_entities_window", bind=True)
def extract_entities_window(self, document_id: str, collection_id: str, start_page: int, end_page: int) -> None:
    try:
        settings = _shared.backend_client.get_collection_settings(collection_id)
        model = _shared._model_for(settings, "extraction")
        if model is None:
            logger.warning(f"No extraction model configured for collection {collection_id}, skipping")
            return

        instructions = settings["instructions"].get("extraction", "")
        pages = _shared._get_pages(document_id)
        window_pages = [page for page in pages if start_page <= page.page_number <= end_page]
        text = _shared._window_text(pages, start_page, end_page)
        logger.info(f"Extracting entities/relations for document {document_id}, pages {start_page}-{end_page}")

        prompt = (
            f"{instructions}\nExtract named entities (type one of: personne, organisation, lieu, date, autre) "
            "and the relations between them from the given text. Respond only with JSON: "
            '{"entities": [{"name": ..., "type": ...}], "relations": [{"from": ..., "to": ..., "type": ..., '
            '"evidence": ...}]}, where evidence is the exact sentence of the text (copied word for word) that '
            "states the relation."
        )
        result = _shared._chat_json(model, prompt.strip(), text)
        entities = result.get("entities", []) if isinstance(result, dict) else []
        relations = result.get("relations", []) if isinstance(result, dict) else []
        logger.info(f"Extracted {len(entities)} entitie(s) and {len(relations)} relation(s)")

        # One call for the window, in place of what an earlier extraction of it recorded (#299): the
        # task run twice leaves the entities, relations and mention counts of one run.
        listed: dict[tuple[str, str], int] = {}
        for entity in entities:
            key = (str(entity["name"]), str(entity["type"]))
            listed[key] = listed.get(key, 0) + 1
        names = {name for name, _ in listed}
        sent_entities = []
        for (name, type_), times_listed in listed.items():
            # Where the name really is in the text of the window (#352): its occurrences, each on its page.
            occurrences = [
                {"page": page.page_number, "start": start, "end": end}
                for page in window_pages
                for start, end in find_mentions(page.content, name)
            ]
            sent_entities.append(
                {
                    "name": name,
                    "type": type_,
                    # The occurrences found when there are some; when the name is nowhere in the text as the
                    # model wrote it, the times the model listed it - listed, with nothing to show.
                    "mentions": len(occurrences) or times_listed,
                    "occurrences": occurrences,
                }
            )
        kept_relations = []
        for relation in relations:
            from_name, to_name = str(relation.get("from")), str(relation.get("to"))
            if from_name not in names or to_name not in names:
                logger.warning(f"Skipping relation with unresolved entity: {relation!r}")
                continue
            kept = {"from_name": from_name, "to_name": to_name, "type": str(relation["type"])}
            # The sentence behind it, only if it really is in the text - a made-up one is dropped, the relation
            # stays without it.
            found = locate_evidence(window_pages, str(relation.get("evidence") or ""))
            if found:
                page_number, excerpt = found
                position = evidence_position(
                    next(p.content for p in window_pages if p.page_number == page_number), excerpt
                )
                kept.update(
                    {
                        "source_page": page_number,
                        "source_excerpt": excerpt,
                        "source_start": position[0] if position else None,
                        "source_end": position[1] if position else None,
                    }
                )
            kept_relations.append(kept)
        _shared.backend_client.replace_entity_window(
            document_id,
            f"pages:{start_page}-{end_page}",
            sent_entities,
            kept_relations,
        )
    except Exception as error:
        _shared._fail(
            document_id,
            f"extract entities for pages {start_page}-{end_page}",
            error,
        )
        raise
