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

## Avec l'échantillonnage (prévu)

À partir de `sampling_min_pages` pages (100 par défaut), trois étapes ne parcourent plus tout le document ; le chunking
parcourt toujours toutes les pages. Un document de 100 pages ou moins est traité comme ci-dessus.

| Étape | Réglage | Appels de chat |
|---|---|---|
| Résumé | `summary_head_percent`, `summary_tail_percent` (ou des plages de pages) | `⌈pages retenues / summary_pages_per_map⌉` + 1, avec `pages retenues = ⌈P × (tête + queue) / 100⌉` |
| QA | `qa_max_questions` (N) | `min(fenêtres sans recouvrement, ⌊N / qa_questions_per_window⌋)` ; au plus N questions |
| Entités | `extraction_percent` | `max(1, ⌈fenêtres × pourcentage / 100⌉)` |

Exemple, 900 pages, résumé 15 % + 15 %, N = 100 questions, 20 % des entités : résumé `⌈270 / 5⌉ + 1 = 55`, QA
`⌊100 / 3⌋ = 33`, entités `⌈897 × 0,2⌉ = 180`, étiquettes 1 : **269 appels au lieu de 1 978** (−86 %).

## Où ce calcul sera utilisé
Une fonction pure `estimate_llm_calls(pages, réglages)` (même module que la sélection des fenêtres, testée contre
`sliding_windows`) donnera ces nombres : l'onglet réglages de la collection affichera « environ N appels pour un document
de 100 / 900 pages » à côté des champs, et le calcul sert de référence pour vérifier qu'un échantillonnage tient son
plafond.
