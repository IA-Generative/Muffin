# worker/document_edit

Worker Celery qui **produit un brouillon d'un document vivant** (ODT ou Markdown, voir l'issue
parente #174) à partir d'une instruction de l'utilisateur. Il ne modifie jamais le fichier source :
il écrit une copie éditée dans RustFS, que l'utilisateur valide (ou non) avant qu'elle devienne une
révision officielle.

Ne parle jamais directement à Postgres : toute lecture/écriture de données passe par les endpoints
internes du backend (`app/backend_client.py`, authentifiés par `WORKER_API_KEY`). Seuls les fichiers
(source et brouillon) sont lus/écrits directement dans RustFS, comme `worker/document_process`.

Dans sa propre queue Celery (`document_edit`), séparée de `document_processing`, `agent_execution` et
`evaluation` : un job d'édition appelle un LLM puis une conversion LibreOffice, ni l'un ni l'autre ne
doit retarder une ingestion ou une réponse de chat.

## État : squelette (#167)

La tâche `edit_document` traverse déjà tout le chemin (queue, contrat, lecture/écriture RustFS, logs
de tâche) mais **n'applique aucune modification** : le brouillon est une copie du point de départ
(`edited: false` dans le résultat). Le reste arrive dans les issues suivantes :

- #168 : l'agent LangGraph qui produit des opérations d'édition typées et les applique à l'ODT en
  place (texte et tableaux, styles du document conservés) ;
- #169 : la conversion du brouillon en PDF d'aperçu (`soffice --headless --convert-to pdf`,
  déjà installé dans l'image) et la boucle de validation côté backend.

## Contrat (`app/contract.py`)

Le backend n'importe jamais le code d'un worker : `app/contract.py` ici et
`backend/app/core/tasks.py` (`enqueue_edit_document`) sont les deux endroits à garder d'accord.

**Entrée** (`EditJobInput`) : `source_storage_key` (fichier courant du document), `prompt`,
`document_id`, `base_revision` (révision sur laquelle l'édition repose, pour que le backend refuse de
promouvoir le brouillon si le document a bougé entre-temps, voir #170), `format` (`odt` ou `md`),
`run_id`, `user_id`, et optionnellement `previous_draft_key` (demande d'ajustement d'un brouillon
précédent : le job part alors de ce brouillon plutôt que du fichier source).

**Sortie** (`EditJobResult`) : `draft_storage_key` (`drafts/{document_id}/{job_id}.{format}`),
`preview_pdf_key` (`null` tant que la conversion n'est pas branchée), `operations_summary`,
`pending_images` (emplacements où une image serait utile - l'agent n'en génère ni n'en récupère
jamais, l'utilisateur dépose le fichier pendant la validation), `edited`.

Le worker est **sans état** : il produit un brouillon et s'arrête, sans `interrupt()` ni
checkpointer. Valider (promouvoir le brouillon en révision), ajuster (nouveau job avec
`previous_draft_key`) ou refuser (supprimer le brouillon) se joue dans le backend.

## Structure

```
app/
  tasks.py           la tâche Celery edit_document
  contract.py        EditJobInput / EditJobResult (modèles Pydantic)
  celery_app.py      app Celery (queue, nom de la tâche - doit matcher backend/app/core/tasks.py)
  storage.py         client S3 (RustFS) : lecture de la source, écriture du brouillon
  backend_client.py  client HTTP vers les endpoints /internal/* du backend
  task_logging.py    capture les logs loguru d'un job et les renvoie au backend
  config.py          Settings (voir docs/environment-variables.md)
```

## Image

`Dockerfile` calqué sur `worker/document_process` : `libreoffice-writer` est installé dans l'image
d'exécution (conversion ODT → PDF de #169) et `HOME=/tmp`, car avec un système de fichiers racine en
lecture seule (Helm) seul `/tmp` est inscriptible, et c'est là que LibreOffice écrit son profil.
Une conversion LibreOffice supporte mal les instances parallèles sur un même profil : #169 donnera à
chaque conversion son propre profil (`-env:UserInstallation`).

## Lancer les tests

```bash
cd worker/document_edit
uv sync --group dev
uv run pytest
uv run ruff check . && uv run ruff format --check .
```
