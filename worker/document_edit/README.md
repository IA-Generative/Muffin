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

## Ce que fait la tâche `edit_document` (`app/tasks.py`, `app/agent.py`)

1. Lit son point de départ dans RustFS : `previous_draft_key` si on lui demande d'ajuster un brouillon,
   sinon `source_storage_key`.
2. Lance l'**agent d'édition**, un petit graphe LangGraph : *plan* (le modèle lit le plan du document
   et répond par une liste d'opérations en JSON), *apply* (on applique ces opérations), avec une
   boucle de reprise bornée (`EDIT_MAX_ATTEMPTS`) : quand une réponse est refusée (JSON invalide,
   opération inconnue, titre inexistant, paragraphe qui porterait une image…), le modèle revoit sa propre
   réponse et le motif exact du refus, et corrige. Le modèle ne voit jamais le document, seulement son
   plan, et ne peut rien faire hors du vocabulaire fermé ci-dessous.
3. Écrit le brouillon dans RustFS (`drafts/{document}/{job}.{format}`) et renvoie le résultat :
   `edited` (vrai si au moins une opération a été appliquée), `operations_summary` (une ligne par
   opération appliquée, ou l'explication du modèle quand il n'y avait rien à changer ou que la demande
   est impossible avec ces opérations), `pending_images`.
4. Si l'agent n'arrive pas à produire une modification applicable, la tâche **échoue** (`EditFailedError`)
   avec un message présentable à l'utilisateur, visible dans les logs de la tâche.

Le plan envoyé au modèle (`outline`) numérote les paragraphes (`¶1`, `¶2`…) et les tableaux (`L1`,
`L2`…) section par section - exactement la numérotation que les opérations utilisent - et signale ce qui
n'est pas modifiable (listes, code, citations, paragraphes portant une image ou une note de bas de page).
Le modèle est celui de `EDIT_LLM_MODEL`, sinon le modèle de chat par défaut du hub, appelé via
`/internal/llm/chat`.

### Aperçu PDF, rapport au backend, images (#169)

- **Aperçu** : pour un ODT réellement modifié, le brouillon est converti en PDF avec LibreOffice
  (`app/preview.py`), stocké à côté (`drafts/{document}/{job}.pdf`) et sa clé renvoyée dans
  `preview_pdf_key`. Chaque conversion a **son propre profil** LibreOffice (`-env:UserInstallation` dans un
  répertoire temporaire) : deux `soffice` qui partageraient un profil se bloquent (le second passe son
  travail au premier et s'arrête). Une conversion qui échoue ou dépasse `PREVIEW_TIMEOUT_SECONDS` fait
  échouer le job : on ne propose pas de valider à l'aveugle. Pas d'aperçu quand rien n'a changé ni pour un
  Markdown (le backend en sert le texte).
- **Rapport** : le worker ne garde aucun état. À la fin d'un job, il appelle le backend
  (`PATCH /api/internal/document-drafts/{task_id}/result` ou `/failure`) ; c'est ce qui rend le brouillon
  « prêt » côté backend. L'identifiant du job est choisi (et enregistré) par le backend avant l'envoi, pour
  éviter que le worker termine avant que l'identifiant existe.
- **Images** (ODT seulement) : une seconde tâche, `insert_images`, sans modèle ni agent. Elle prend un
  brouillon et les fichiers que l'utilisateur a déposés pour les emplacements signalés dans
  `pending_images`, insère chaque image dans un paragraphe à elle (à l'emplacement demandé, ou en fin de
  document), la dimensionne d'après ses pixels (96 dpi, jamais plus large que 16 cm) et rend un nouvel
  aperçu. PNG, JPEG et GIF uniquement (`app/image_size.py` lit leurs en-têtes, sans bibliothèque d'image).

Pas encore fait : le déclenchement d'un job depuis l'agent de recherche (#171). Les images ne sont jamais
insérées par l'agent : il les décrit dans `pending_images` avec leur emplacement souhaité.

## Opérations d'édition (`app/operations.py`, `app/odt_editor.py`, `app/markdown_editor.py`)

Un seul vocabulaire pour les deux formats : l'agent ne sait pas s'il édite un ODT ou un Markdown.

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

Remplacer un paragraphe qui porte une **image ou une note de bas de page** est refusé (le texte seul
serait remplacé et l'image ou la note disparaîtrait) ; le supprimer volontairement reste possible.

Pas encore pris en charge côté ODT : les éléments de liste (ni lecture ni écriture), le contenu imbriqué
dans une `text:section`, les cellules fusionnées, les images (elles passent par la validation, #169).

### Markdown (`app/markdown_editor.py`)

Les modifications se font sur les lignes sources, localisées avec la carte des blocs de `markdown-it` :
tout ce qu'une opération ne nomme pas reste identique octet pour octet (autres paragraphes, listes,
blocs de code - un `#` dans un bloc de code n'est pas un titre -, citations, HTML, fins de ligne `\r\n`
ou absence de saut de ligne final). Un « paragraphe » est un bloc paragraphe de premier niveau ; les
titres ATX (`#`) et setext (`===`) sont reconnus. Seul un tableau ciblé par une opération est réécrit,
en tableau GFM aligné (les alignements `:--`, `:-:`, `--:` sont conservés ; `|` et sauts de ligne dans
une cellule sont échappés en `\|` et `<br>`). En Markdown la première ligne d'un tableau est son
en-tête : insérer au-dessus ou la supprimer est refusé, car cela ferait silencieusement d'une autre
ligne l'en-tête.

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
`pending_images` (emplacements où une image serait utile, avec une `description` et la `section` /
`after_paragraph` souhaités - l'agent n'en génère ni n'en récupère jamais, l'utilisateur dépose le fichier
pendant la validation), `edited`.

Le worker est **sans état** : il produit un brouillon et s'arrête, sans `interrupt()` ni
checkpointer. Valider (promouvoir le brouillon en révision), ajuster (nouveau job avec
`previous_draft_key`) ou refuser (supprimer le brouillon) se joue dans le backend.

## Structure

```
app/
  tasks.py           la tâche Celery edit_document
  agent.py           l'agent LangGraph : prompt, plan, application, reprise sur refus
  operations.py      le vocabulaire des opérations d'édition (modèles Pydantic)
  odt_editor.py      applicateur ODT en place (+ plan du document)
  markdown_editor.py applicateur Markdown (+ plan du document)
  editing.py         point d'entrée commun aux deux formats
  edit_types.py      erreurs, résultat et rendu du plan, partagés par les deux applicateurs
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
