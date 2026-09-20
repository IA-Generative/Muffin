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

            entity_ids: dict[str, str] = {}
            for entity in entities:
                created = _shared.backend_client.upsert_entity(
                    collection_id, document_id, str(entity["name"]), str(entity["type"])
                )
                entity_ids[str(entity["name"])] = created["id"]

            for relation in relations:
                from_id = entity_ids.get(str(relation.get("from")))
                to_id = entity_ids.get(str(relation.get("to")))
                if from_id is None or to_id is None:
                    logger.warning(f"Skipping relation with unresolved entity: {relation!r}")
                    continue
                _shared.backend_client.create_relation(
                    collection_id, document_id, from_id, to_id, str(relation["type"])
                )
        except Exception as error:
            _shared._fail(
                document_id,
                f"extract entities for pages {start_page}-{end_page}",
                error,
            )
            raise
