# Appels au LLM pour indexer un document

Combien d'appels au modèle l'indexation d'un document de `P` pages demande, étape par étape. Les valeurs par défaut sont
celles de `PIPELINE_WINDOW_DEFAULTS` (`worker/document_process/app/tasks/_shared.py`) et de `PipelineWindowsOut`
(`backend/app/schemas/collection.py`) ; chaque réglage se change par collection (onglet réglages).

L'extraction (OCR, parsing) n'appelle aucun modèle. Les appels de **chat** sont ceux qui coûtent cher et qui prennent du
temps ; les appels d'**embedding** sont comptés à part.

## Les formules (aujourd'hui)

Une fenêtre glissante de `w` pages avançant de `s` pages donne `fenêtres(P, w, s) = 1` si `P ≤ w`, sinon
`⌈(P − w) / s⌉ + 1` (c'est `sliding_windows`, `app/windows.py`).

| Étape | Appels de chat | Réglages (défaut) |
|---|---|---|
| **Chunking** | `⌈P / chunking_window_pages⌉` si la stratégie est `llm` (fenêtres côte à côte, sans recouvrement) ; **0** pour les autres stratégies | `chunking_window_pages` (2) |
| **Résumé** | `m = ⌈P / summary_pages_per_map⌉` appels « map », plus **1** appel « reduce » si `m > 1` | `summary_pages_per_map` (5) |
| **Étiquettes** (`tag_document`) | **1** | |
| **QA** | `fenêtres(P, qa_window_pages, qa_slide_pages)`, un appel par fenêtre | `qa_window_pages` (2), `qa_slide_pages` (1) |
| **Entités** | `fenêtres(P, extraction_window_pages, extraction_slide_pages)`, un appel par fenêtre | `extraction_window_pages` (4), `extraction_slide_pages` (1) |
| **Collection** (description, étiquettes, QA de collection) | jusqu'à **4**, et seulement quand le résumé du document change ce que dit la collection | |

Appels d'**embedding** : `⌈chunks / EMBED_BATCH_SIZE⌉` pour les chunks (64 par appel), **1** pour le résumé, et un par
question générée pour les QA (`fenêtres × qa_questions_per_window` au plus, 3 par défaut).

**Total de chat** = chunking (si `llm`) + résumé + 1 + QA + entités (+ jusqu'à 4 pour la collection).

### Exemples, réglages par défaut

| Pages | Résumé | QA | Entités | Chunking `llm` | **Total** (hors chunking) | Embeddings de QA |
|---:|---:|---:|---:|---:|---:|---:|
| 10 | 3 | 9 | 7 | 5 | **20** | 27 |
| 100 | 21 | 99 | 97 | 50 | **218** | 297 |
| 101 | 22 | 100 | 98 | 51 | **221** | 300 |
| 900 | 181 | 899 | 897 | 450 | **1 978** | 2 697 |

(Total = résumé + 1 étiquette + QA + entités ; avec le chunking `llm`, ajouter la colonne correspondante.)

Les fenêtres des QA et des entités se recouvrent (glissement de 1 page) : c'est ce qui les rend nombreuses.

## Avec l'échantillonnage (prévu, #372)

À partir de `sampling_min_pages` pages (100 par défaut), trois étapes ne parcourent plus tout le document ; le chunking
parcourt toujours toutes les pages. Un document de 100 pages ou moins est traité comme ci-dessus.

Les fenêtres tirées sont **sans recouvrement** (glissement = taille de fenêtre) : « 20 % » veut dire 20 % des pages. Avec les
fenêtres actuelles, qui se recouvrent, 20 % des fenêtres en couvriraient environ 80 % des pages.

| Étape | Réglage | Appels de chat |
|---|---|---|
| Résumé | `summary_percent` (réparti moitié début, moitié fin), ou `summary_head_percent` + `summary_tail_percent`, ou des plages de pages (`summary_page_ranges`) | `⌈pages retenues / summary_pages_per_map⌉` + 1, avec `pages retenues = ⌈P × pourcentage / 100⌉` |
| QA | `qa_max_questions` (N), par document | `min(⌈P / qa_window_pages⌉, ⌊N / qa_questions_per_window⌋)` ; au plus N questions |
| Entités | `extraction_percent`, `extraction_max_windows` (optionnel) | `min(max(1, ⌈⌈P / extraction_window_pages⌉ × pourcentage / 100⌉), extraction_max_windows)` |

Exemple, 900 pages, résumé 30 % (15 % + 15 %), N = 100 questions, 20 % des entités : résumé `⌈270 / 5⌉ + 1 = 55`, QA
`⌊100 / 3⌋ = 33`, entités `⌈⌈900 / 4⌉ × 0,2⌉ = 45`, étiquettes 1 : **134 appels au lieu de 1 978** (−93 %).

## Où ce calcul est utilisé
Une fonction unique dans le backend (`estimate_llm_calls`, `backend/app/core/indexing_cost.py`) donne ces nombres par
`GET /api/collections/{id}/indexing-estimate?pages=N`, selon les réglages de la collection ; l'onglet réglages l'appellera
(#375) : « environ N appels pour un document de 100 / 900 pages » à côté des champs. Les cas de référence
(`docs/indexing-llm-calls-cases.json` : pages, réglages → appels) sont vérifiés par le test du backend et par un test du
worker qui compte les tâches réellement envoyées (`tests/test_llm_call_cases.py`) : le calcul affiché et le travail fait ne
peuvent pas diverger. Aujourd'hui le worker ne lit que les cas qui parcourent tout le document ; ceux qui en lisent une
partie le seront avec #374, quand les étapes appliquent les réglages.

## Les réglages (`pipeline_windows`, par collection)
`sampling_min_pages` (100), `summary_mode` (`all` / `percent` / `pages`), `summary_percent` (30), `summary_head_percent` et
`summary_tail_percent` (début et fin séparés, qui remplacent `summary_percent`), `summary_page_ranges` (« 1-5, 40-45 »),
`qa_max_questions`, `extraction_percent` (100), `extraction_max_windows`. Les valeurs par défaut lisent tout : rien ne
change tant qu'on ne les règle pas. Le backend refuse les valeurs qui n'ont pas de sens, y compris celles qui ne le sont
qu'ensemble (début + fin supérieurs à 100 %, un mode « pages » sans page).
