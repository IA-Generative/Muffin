"""Tâche d'extraction d'entités et de relations nommées.

Parcourt une fenêtre de pages et demande au LLM d'extraire les entités
(personne, organisation, lieu, date, autre) et les relations entre elles.
Les entités sont upsertées (déduplication par nom), les relations lient
les entités résolues.
"""

from loguru import logger

from app.celery_app import celery_app
from app.task_logging import capture_task_logs
from app.tasks import _shared


@celery_app.task(name="app.tasks.extract_entities_window", bind=True)
def extract_entities_window(self, document_id: str, collection_id: str, start_page: int, end_page: int) -> None:
    with capture_task_logs(self.request.id):
        try:
            settings = _shared.backend_client.get_collection_settings(collection_id)
            model = _shared._model_for(settings, "extraction")
            if model is None:
                logger.warning(f"No extraction model configured for collection {collection_id}, skipping")
                return

            instructions = settings["instructions"].get("extraction", "")
            text = _shared._window_text(_shared._get_pages(document_id), start_page, end_page)
            logger.info(f"Extracting entities/relations for document {document_id}, pages {start_page}-{end_page}")

            prompt = (
                f"{instructions}\nExtract named entities (type one of: personne, organisation, lieu, date, autre) "
                "and the relations between them from the given text. Respond only with JSON: "
                '{"entities": [{"name": ..., "type": ...}], "relations": [{"from": ..., "to": ..., "type": ...}]}.'
            )
            result = _shared._chat_json(model, prompt.strip(), text)
            entities = result.get("entities", []) if isinstance(result, dict) else []
            relations = result.get("relations", []) if isinstance(result, dict) else []
            logger.info(f"Extracted {len(entities)} entitie(s) and {len(relations)} relation(s)")

            # One call for the window, in place of what an earlier extraction of it recorded (#299): the
            # task run twice leaves the entities, relations and mention counts of one run.
            mentions: dict[tuple[str, str], int] = {}
            for entity in entities:
                key = (str(entity["name"]), str(entity["type"]))
                mentions[key] = mentions.get(key, 0) + 1
            names = {name for name, _ in mentions}
            kept_relations = []
            for relation in relations:
                from_name, to_name = str(relation.get("from")), str(relation.get("to"))
                if from_name not in names or to_name not in names:
                    logger.warning(f"Skipping relation with unresolved entity: {relation!r}")
                    continue
                kept_relations.append({"from_name": from_name, "to_name": to_name, "type": str(relation["type"])})
            _shared.backend_client.replace_entity_window(
                document_id,
                f"pages:{start_page}-{end_page}",
                [{"name": name, "type": type_, "mentions": count} for (name, type_), count in mentions.items()],
                kept_relations,
            )
        except Exception as error:
            _shared._fail(
                document_id,
                f"extract entities for pages {start_page}-{end_page}",
                error,
            )
            raise
