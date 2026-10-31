"""Description d'une collection, faite d'un échantillon de ses fichiers (#457).

- ``scan_undescribed_collections`` : tâche planifiée, demande la description des collections qui n'en ont pas.
- ``describe_collection`` : tire au hasard quelques fichiers de la collection, résume l'échantillon puis écrit la
  description. Indépendante des résumés de fichiers : elle n'attend aucun fichier en particulier.
"""

import random

import redis
from loguru import logger

from app.celery_app import celery_app
from app.config import settings as worker_settings
from app.tasks import _shared
from app.tasks.collection import _index_description, _publish_description

UNCHANGED = "INCHANGÉE"

# What the description of a collection is: it serves to decide whether to look in the collection for a question, as the
# routing of the search does when it picks the collections from their description.
WHAT_A_DESCRIPTION_IS = (
    "La description d'une base documentaire (une collection) dit ce que contient la base dans son ensemble, pour "
    "qu'un lecteur ou un assistant puisse décider s'il doit la consulter pour répondre à une question : les "
    "sujets traités, le type de documents quand il aide à choisir, la période ou le contexte, et à qui ils "
    "s'adressent. Elle ne contient que de l'information : on sait déjà que c'est une base de documents, donc elle"
    " ne commence ni par « Base documentaire », « Collection de », « Ensemble de » ni par « Ces documents », et "
    "ne contient aucune formule (« couvre notamment », « s'adresse principalement à », « s'inscrit dans »). Elle "
    "commence directement par le sujet. Elle ne cite aucun nom de fichier, ne parle ni d'« extraits » ni d'« "
    "échantillon », et ne généralise pas au-delà du résumé. Elle fait 2 à 3 phrases courtes et concrètes, avec "
    "les termes précis du domaine (organismes, textes, procédures). Exemple de ton, sur un autre domaine : « "
    "Règlement de voirie et arrêtés de circulation d'une métropole : stationnement, chantiers, déviations, "
    "redevances d'occupation du domaine public. Pour les services techniques et les entreprises de travaux. »"
)


def sample_excerpts(collection_id: str, rng: random.Random) -> list[str]:
    """The beginning of files of the collection that say something of it. A source is sometimes cut into hundreds of
    files of the same name, so one drawn among the files would see a single document: the draw is among the distinct
    names (one file per name, in turn), and a file with too little text to count is passed over."""
    by_name: dict[str, list[str]] = {}
    for document in _shared.backend_client.list_collection_documents(collection_id):
        by_name.setdefault(document["name"], []).append(document["id"])
    for ids in by_name.values():
        rng.shuffle(ids)
    names = list(by_name)
    rng.shuffle(names)

    count = worker_settings.DESCRIBE_SAMPLE_FILES
    excerpts: list[str] = []
    while names and len(excerpts) < count:
        for name in list(names):
            if len(excerpts) == count:
                break
            ids = by_name[name]
            while ids:
                text = "\n\n".join(page.content for page in _shared._get_pages(ids.pop())).strip()
                if len(text) >= worker_settings.DESCRIBE_MIN_CHARS:
                    excerpts.append(f"### {name}\n{text[: worker_settings.DESCRIBE_SAMPLE_CHARS]}")
                    break
            if not ids:
                names.remove(name)
    return excerpts


def propose_description(model: str, instructions: str, current: str, excerpts: list[str]) -> str | None:
    """The description to give the collection, None when the one it has stays: a summary of the sample, then the
    description made from that summary - or, when there is already one, kept unless it is false, empty of meaning or
    misses an important subject of the sample."""
    summary = _shared._chat(
        model,
        "Tu résumes des extraits de documents d'une même base documentaire. Rédige un seul résumé factuel (4 à 6 "
        "phrases) de ce que ces documents ont en commun : sujets, type de documents, public. Réponds uniquement "
        "avec le résumé.",
        "\n\n".join(excerpts),
    ).strip()
    if not current:
        system = (
            f"Tu écris la description d'une base documentaire. {WHAT_A_DESCRIPTION_IS} Tu la rédiges d'après le "
            "résumé d'un échantillon de ses documents. Réponds uniquement avec la description."
        )
        user_content = summary
    else:
        system = (
            f"Tu tiens à jour la description d'une base documentaire. {WHAT_A_DESCRIPTION_IS} On te donne la "
            "description actuelle et le résumé d'un échantillon de ses documents. Change la description seulement "
            "si elle est fausse, vide de sens ou qu'il lui manque un sujet important que l'échantillon montre ; une "
            "description juste, même plus courte ou formulée autrement, reste telle quelle : réponds alors "
            f"exactement {UNCHANGED}. Sinon réponds uniquement avec la description corrigée, qui garde tout ce qui "
            "était juste dans l'ancienne, surtout ce qui identifie la base (organisme, service, territoire, "
            "périmètre, période) : ce que l'échantillon ne peut pas montrer ne doit pas disparaître."
        )
        user_content = f"Description actuelle :\n{current}\n\nRésumé de l'échantillon :\n{summary}"
    verdict = _shared._chat(model, f"{instructions}\n{system}".strip(), user_content).strip()
    if not verdict or verdict.upper().startswith(UNCHANGED) or verdict == current:
        return None
    return verdict


# Celery's lowest priority, as the other tasks of the enrichment are sent with when they are not waited for.
LOW_PRIORITY = 9


def _claim_description(collection_id: str) -> bool:
    """Whether this pass is the first in DESCRIBE_RETRY_HOURS to ask for the collection (and so, of several replicas'
    beats, the only one)."""
    client = redis.Redis.from_url(worker_settings.REDIS_URL)
    return bool(
        client.set(f"describe-collection:{collection_id}", "1", nx=True, ex=worker_settings.DESCRIBE_RETRY_HOURS * 3600)
    )


@celery_app.task(name="app.tasks.scan_undescribed_collections")
def scan_undescribed_collections() -> int:
    """Asks for the description of every collection of Muffin that has files and none yet. Returns how many were
    asked for."""
    asked = 0
    for collection_id in _shared.backend_client.list_undescribed_collections():
        if _claim_description(collection_id):
            describe_collection.apply_async(args=[collection_id], priority=LOW_PRIORITY)
            asked += 1
    if asked:
        logger.info(f"Description: {asked} collection(s) without one asked for")
    return asked


@celery_app.task(name="app.tasks.describe_collection", bind=True)
def describe_collection(self, collection_id: str) -> None:
    """The description of a collection, made from a random sample of its files: no summary, no file in particular is
    waited for. Made when it has none, otherwise kept unless the sample shows it is wrong or incomplete. Its embedding
    goes to the index that routes a question to a collection, including a description that stays when it was never put
    there. No QA pairs of the collection, which are generated when a description changes by the pipeline's own task."""
    settings = _shared.backend_client.get_collection_settings(collection_id)
    model = _shared._model_for(settings, "summary")
    if model is None:
        logger.warning(f"No model available to describe collection {collection_id}, skipping")
        return
    excerpts = sample_excerpts(collection_id, random.Random())
    if not excerpts:
        logger.info(f"Collection {collection_id} has no file with enough text to be described")
        return

    metadata = _shared.backend_client.get_collection_metadata(collection_id)
    current = (metadata["description"] or "").strip()
    proposed = propose_description(model, settings["instructions"].get("summary", ""), current, excerpts)
    if proposed is not None:
        _publish_description(collection_id, proposed)
    else:
        logger.info(f"Description for collection {collection_id} left unchanged")
        if current and not metadata.get("description_indexed", True):
            _index_description(collection_id, current)
