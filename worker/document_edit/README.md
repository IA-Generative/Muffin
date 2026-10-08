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

## État

La tâche `edit_document` traverse tout le chemin (queue, contrat, lecture/écriture RustFS, logs de
tâche) mais **n'applique encore aucune modification** : le brouillon est une copie du point de départ
(`edited: false` dans le résultat). Ce qui existe déjà pour #168, sans être branché à la tâche :

- `app/operations.py` : le vocabulaire fermé des opérations d'édition (voir plus bas) ;
- `app/odt_editor.py` : l'applicateur, qui exécute ces opérations sur un ODT **en place**.

Reste à faire : brancher l'agent LangGraph qui produit ces opérations à partir du prompt et appelle
l'applicateur (#168, dernière étape), l'applicateur Markdown (#168), puis la conversion du brouillon
en PDF d'aperçu (`soffice --headless --convert-to pdf`, déjà installé dans l'image) et la boucle de
validation côté backend (#169).

## Opérations d'édition ODT (`app/operations.py`, `app/odt_editor.py`)

Une opération désigne sa cible par le **texte du titre de sa section** plus un index à partir de 1
(« le 2e paragraphe sous *Contacts* », « le tableau 1 de *Matériel par profil* »), pas par un
identifiant interne : ça reste valable si le document a été retouché à la main depuis sa lecture, et
c'est ce qu'un modèle sait produire à partir du plan du document. Le titre se compare sans tenir
compte de la casse ni des espaces ; `occurrence` départage deux titres identiques ; un titre `null`
désigne le début du document. Une section va d'un titre au titre suivant, quel que soit son niveau.

| Opération | Effet |
|---|---|
| `replace_paragraph` | remplace le texte du n-ième paragraphe (son style est conservé, la mise en forme interne de l'ancien texte non) |
| `insert_paragraph` | ajoute un paragraphe après le n-ième (0 : sous le titre, absent : en fin de section) |
| `delete_paragraph` | supprime le n-ième paragraphe |
| `insert_section` | ajoute un titre (niveau 1 à 6) et ses paragraphes après une section, sous-sections comprises, ou en fin de document |
| `set_cell` | modifie une cellule (ligne, colonne) ; une cellule numérique à qui l'on donne un nombre reste numérique |
| `insert_row` / `delete_row` | ajoute une ligne (après la n-ième, 0 : tout en haut, absent : en bas) ou en supprime une |
| `insert_column` / `delete_column` | idem pour une colonne |
| `insert_table` | crée un tableau (première ligne = en-tête) |

Le fichier n'est **jamais régénéré** : `content.xml` est modifié via `odfdo` et réécrit, donc tout ce
qu'aucune opération ne nomme (styles, images, notes de bas de page, listes, sommaires) est reporté tel
quel. Le nouveau contenu emprunte les styles de ses voisins : un paragraphe ajouté reprend celui du
paragraphe voisin (sinon le style le plus courant du document), un titre celui d'un titre du même
niveau (sinon le style nommé `Heading N` du document), une ligne ou une colonne ajoutée celui d'une
ligne de données ou de la colonne voisine (pas de l'en-tête), un tableau neuf ceux du premier tableau
existant. Le résultat est donc tout-ou-rien : les opérations s'exécutent sur une copie en mémoire et
rien n'est produit si l'une échoue (`OperationError`, avec son numéro et un message lisible, qui
liste les titres disponibles quand un titre est introuvable).

Pas encore pris en charge : les éléments de liste (ni lecture ni écriture), le contenu imbriqué dans
une `text:section`, les cellules fusionnées, les images (elles passent par la validation, #169).

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
