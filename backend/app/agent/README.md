# backend/app/agent

L'agent de recherche : le graphe LangGraph qui mène une question de l'utilisateur jusqu'à une réponse citée, en passant par un
plan, la recherche multi-collections et, pour une réponse difficile, une vérification que chaque affirmation est étayée par une
source (grounding).

## Où il tourne

**Dans le backend**, pas dans un worker. Un run est une tâche de fond de la boucle d'événements du backend (`runner.py`) qui confie
son graphe - des nœuds synchrones - à un thread, pour ne jamais bloquer la boucle qui sert les utilisateurs. Il survit à la requête
qui l'a créé ; l'interface suit le run et ses événements comme avant.

- **Le jeton de l'utilisateur** (`user_token.py`) : le `POST /api/runs` le prend à la requête (jeton porteur, ou jeton d'accès de la
  session) et le garde **en mémoire pour la durée du run**, dans une variable de contexte - jamais dans l'état du graphe (que le
  checkpointer écrit dans Redis), ni dans un événement, un log ou la base. Un outil qui doit appeler un service au nom de
  l'utilisateur le demande avec `current_user_token()` ; les branches parallèles de la recherche le voient aussi. Il n'est pas
  renouvelé : un run dure de quelques secondes à quelques minutes.
- **Les appels au backend** (`backend_client.py`, `runtime.py`) passent par ses propres routes `/api/internal/*`, **en mémoire** (transport
  ASGI), avec la clé `WORKER_API_KEY` du backend : la logique de chaque route reste où elle est, rien n'est recopié. C'est une étape :
  des appels directs aux services remplaceront ces routes au fil du temps. La réponse en streaming ne passe pas par une réponse HTTP
  (elle n'arrive qu'entière en mémoire) : elle lit le générateur de la route.
- **Ce que ça coûte** : un run ne survit pas au redémarrage du pod qui l'exécute. Un run qui n'avance plus depuis 10 minutes est marqué
  « échoué » (au démarrage d'un pod et toutes les 5 minutes), pour que l'utilisateur soit prévenu. Le nombre de runs qu'un pod exécute
  en même temps est borné (`MAX_CONCURRENT_RUNS`) : les autres attendent leur tour.
- **L'annulation** (`cancellation.py`) : `cancel_requested` sur le run, que chaque nœud regarde à son début, quel que soit le pod ; le pod
  qui exécute le run est aussi prévenu directement, pour que l'attente du worker SQL s'arrête à son prochain regard.

Ne parle jamais directement à Postgres/Qdrant : toute lecture/écriture passe par les routes internes. Exceptions : SearXNG
(`searxng_client.py`), appelé directement par l'outil `web_search` - aucune donnée utilisateur n'y est stockée, ce n'est qu'un
aller-retour HTTP - et le worker SQL (`tabular_query`), à qui l'agent envoie ses requêtes par la queue Celery `tabular_sql`.

## Le graphe (`app/graph/graph.py`)

Un seul appel au modèle décide de tout (`plan`), la recherche qui suit est du code, un second appel écrit la réponse. Le
dessin est dans [docs/agent-execution-graph.md](../../../docs/agent-execution-graph.md) ; `backend/scripts/draw_agent_graph.py`
le régénère depuis le graphe compilé.

1. `prepare` - charge la liste des collections auxquelles l'utilisateur a accès (**la** barrière de permission : le plan
   ne fait que restreindre à l'intérieur de cette liste, jamais l'élargir), tronque l'historique, et - seulement si le message
   contient un verbe de modification ou de création - charge ce que l'utilisateur peut modifier ou ce où il peut créer.
   Avec beaucoup de collections, le catalogue donné au plan est réduit par le pré-filtre vectoriel (sans modèle).
2. `plan` (**appel n°1**) - lit le message à la lumière des derniers tours et rend un JSON : `mode` (`direct`, `clarify`,
   `help`, `edit`, `create`, `search`), et pour `search` la question autonome, 1 à 4 requêtes indépendantes avec leur outil, les
   collections à chercher et la complexité. `direct` porte la réponse elle-même (salutation, identité) : le run s'arrête là,
   avec un seul appel. `clarify` termine le run sur 1 à 4 questions à choix (voir
   [docs/assistant-questions.md](../../../docs/assistant-questions.md)) ; sans personne à qui demander, ou après
   `MAX_QUESTION_ROUNDS` questions de suite, il continue et dit ce qu'il suppose. Un identifiant que le modèle cite et qui n'est
   pas dans les listes du backend est écarté, et un plan inutilisable est une simple recherche de la question.
3. `answer_help` - répond à une question sur l'utilisation de Muffin avec le guide intégré (appel n°2).
4. Sous-graphe `edit` (`edit_resolve` → `edit_request` → `edit_wait` → `edit_report`) et sous-graphe `create`
   (`create_resolve` → `create_write`) - voir les sections dédiées plus bas. Aucun ne revient à la recherche.
5. `research_task` (fan-out dynamique via `Send`, une branche par requête du plan, en parallèle, borné par `MAX_PARALLEL_TASKS` et
   `MAX_TOTAL_TASKS`) - exécute un outil par requête : `search`, `page_content`, `list_documents`, `collection_summary`,
   `list_collections`, `tabular_query`, `time`, `web_search`. **Aucun appel au modèle pour choisir les collections** : la
   recherche se fait dans celles du plan (et celles que l'utilisateur a épinglées) avec leurs sous-collections
   (`include_descendants`), ou dans toutes si le plan n'en a pas choisi. Pour `search`, les trois niveaux (une question déjà
   répondue, les résumés des documents, les passages) sont interrogés en même temps. `web_search` (SearXNG) n'est jamais
   proposé au plan ni exécuté sauf si le run a activé la recherche web (toggle du composer de chat, désactivé par défaut).
6. `merge_evidence` → `gate` - décide **en code** si les preuves suffisent (`GATE_MIN_EVIDENCE`, `GATE_MIN_SCORE`). Pas assez et
   le plan avait restreint les collections : `widen_search` refait les recherches dans toutes, une fois. Toujours pas assez :
   la réponse dit ce qui n'a pu être établi (sans appel au modèle quand il n'y a aucun extrait).
7. `build_answer_context` → `generate_answer` (**appel n°2**, en streaming) - réponse finale avec citations.
8. `ground_check` (**appel n°3, optionnel**) - hors du graphe : `AgentService` le lance une fois le run `completed`, seulement pour
   une réponse difficile (plusieurs requêtes ou complexité forte), et enregistre le verdict sur le run
   (`PATCH /internal/runs/{id}/grounding`). L'utilisateur ne l'attend pas.

Un message simple coûte donc 2 appels (3 avec le contrôle), une salutation 1, hors la boucle SQL de `tabular_query`. Le graphe
peut être annulé (`cancel_requested` sur le run) : chaque nœud le vérifie à son début. Une clarification ne met plus le run en pause
(#344) : les questions sont enregistrées avec le message de l'assistant, la réponse de l'utilisateur démarre un nouveau run qui
la lit avec l'historique de la conversation. Le checkpointer LangGraph sur Redis ne sert plus qu'à reprendre un run qui attendait
déjà une réponse avant ce changement.

## Déléguer une modification à l'agent d'édition (sous-graphe `edit`)

L'agent de recherche ne modifie jamais rien lui-même, ni ne parle directement à l'agent d'édition :
c'est le backend qui porte l'état d'une proposition (brouillon, verrou du document, tâche), et c'est
cet état que l'interface d'examen affiche déjà. Le circuit est donc le suivant :

1. **Le plan** (`prepare` puis `plan`). Un filtre peu coûteux d'abord : le message
   doit contenir un verbe de modification (ajoute, supprime, remplace, corrige… et leurs équivalents
   anglais), sinon ni le backend ni le modèle ne sont sollicités. Ensuite l'agent demande au backend la
   liste des documents vivants **que l'utilisateur peut modifier** (`GET /internal/runs/{id}/editable-
   documents`) ; s'il n'y en a aucun, le run continue comme une question. Un appel au modèle décide s'il
   s'agit bien d'une modification et de quel document. Le modèle ne choisit qu'**parmi les documents
   proposés** : un identifiant qu'on ne lui a pas offert n'est jamais suivi (le run reprend alors comme une
   question), et en cas de doute `edit` est faux - répondre à une question est sans danger, modifier un
   document non. Si plusieurs documents peuvent convenir sans que rien n'indique lequel, l'agent le
   demande à l'utilisateur au lieu de deviner.
2. **`edit_request`, `edit_wait`, `edit_report`**. Ils demandent au backend de créer la demande (`POST /internal/runs/{id}/edit-
   requests`), qui crée le brouillon, prend le verrou du document et envoie le job à l'agent d'édition,
   puis **suit le brouillon** (`GET …/edit-requests/{document}`, toutes les `EDIT_POLL_SECONDS`, pendant
   au plus `EDIT_WAIT_SECONDS`) en vérifiant l'annulation à chaque tour. Lire le brouillon renouvelle son
   verrou, donc la proposition ne s'éteint pas pendant l'attente. La réponse reprend la conclusion : ce
   qui a changé, ou l'explication de l'agent d'édition quand il ne pouvait pas modifier, ou l'échec, ou
   « travaille encore » si le délai est dépassé.
3. **Les droits sont ceux de l'utilisateur du run, décidés côté backend** à partir du instantané du run
   (utilisateur, groupes, drapeau administrateur) : le propriétaire de la collection, ou un administrateur
   de la plateforme sur une collection qu'il peut déjà voir. Ni la liste proposée au modèle ni la création
   ne reposent sur quoi que ce soit que ce worker fournit. Un refus (document verrouillé par quelqu'un,
   proposition déjà en attente, droit insuffisant) est dit à l'utilisateur tel quel.
4. Le run termine avec `edit_proposal` (`{collection_id, document_id, document_name}`), enregistré avec la
   réponse : le chat en fait une **carte distincte** de la réponse, qui ouvre la fenêtre d'examen
   (valider, ajuster, refuser). Rien n'est écrit dans la collection avant cette validation.

## Pièges connus

Deux bugs rencontrés en ajoutant `web_search`, tous deux invisibles en tests unitaires - seul un
run réel de bout en bout contre la stack dev (utilisateur sans aucune collection accessible,
`web_search_enabled=true`) les a fait apparaître : la réponse revenait sans aucune citation
`web_search`, alors que l'outil aurait dû être utilisé.

- **`replan_research.py` figeait `tool="search"` pour toute tâche replanifiée.** La boucle
  "couverture insuffisante → replan" (`evaluate_coverage` → `replan_research`) est justement le
  scénario principal décrit pour déclencher `web_search` (accès documentaire épuisé), mais elle ne
  pouvait jamais l'atteindre puisque le tool était toujours forcé à `"search"`. Corrigé en laissant
  le LLM choisir l'outil parmi le même ensemble activé/désactivé que `decompose_query.py`.
- **`evaluate_coverage.py` classait un jeu de preuves 100% `web_search` comme une simple recherche
  "meta" (au même titre que `list_collections`/`collection_summary`/...), donc jugée complète sans
  évaluation de pertinence.** Un résultat web est une preuve de contenu au même titre qu'un chunk
  de document, pas une recherche méta - il doit passer par le même jugement de suffisance. Corrigé
  via l'ensemble `_CONTENT_TOOLS = {"search", "web_search"}`.

À garder en tête pour tout futur outil de type « recherche » ajouté au graphe : vérifier qu'il est classé parmi les outils de
contenu du `gate` (`_CONTENT_TOOLS` dans `nodes/gate.py`) - un test unitaire isolé sur le nœud concerné ne suffit pas à le
détecter, il faut un run bout en bout.

## Structure

```
backend/app/agent/
  graph/
    graph.py       assemblage du graphe (add_node / add_conditional_edges)
    state.py       AgentState (état partagé) et ResearchTaskInput (payload du fan-out)
    nodes/         un fichier par nœud du graphe (voir la liste ci-dessus)
    routing/       conditions.py - branchement après le plan et le gate, fan-out
    services/      llm.py (appels LLM), scope.py (collections à chercher), vdb_router.py (catalogue montré au plan),
                   tool_guide.py, authoring.py, evidence.py, document_resolver.py, events.py
  runner.py        les runs : tâches de fond, bornées, annulables, runs orphelins échoués
  service.py       charge le run, construit l'état initial, lance le graphe, enregistre le résultat
  runtime.py       le pont entre les threads des runs et la boucle du backend
  backend_client.py client des routes /api/internal/* du backend (en mémoire)
  user_token.py    le jeton de l'utilisateur, en mémoire, le temps du run
  cancellation.py  annulation d'un run
  searxng_client.py client HTTP vers SearXNG (outil web_search)
  config.py        Settings, dont les budgets d'exécution (voir docs/environment-variables.md)
```

## Développer

```bash
cd backend
uv sync
uv run pytest -q tests/agent   # tests (faux backend client, pas de vrais appels réseau)
uv run ruff check . && uv run ruff format --check .
```

Le graphe se dessine avec `uv run python scripts/draw_agent_graph.py`.

## Données tabulaires - l'outil `tabular_query` (#433)

L'agent interroge les fichiers tabulaires (CSV, XLSX, XLS, ODS, JSON, Parquet...) en **SQL**, sur leurs vraies
feuilles, sans exécuter de SQL ni lire de fichier lui-même : chaque requête part au worker `worker/tabular` (#432).

- **Catalogue** (`app/graph/services/tabular_catalog.py`) : les documents tabulaires des collections retenues, tels
  que le backend les liste (c'est lui qui applique les droits). Chaque fichier est un schéma (`f1`, `f2`...) et chaque
  feuille une table : `f1."Ventes"`. Les feuilles, colonnes (type SQL) et quelques valeurs d'exemple sont donnés au
  modèle comme des **données**, jamais des instructions. Un document sans copie Parquet (indexé avant #431) est
  annoncé « à réindexer » et jamais interrogé.
- **Boucle** (`app/graph/services/tabular_query.py`) : le modèle enchaîne au plus `TABULAR_MAX_STEPS` appels de
  `query_data(sql, files?)`, un objet JSON par tour (le client de chat n'a pas d'appel d'outil natif). Un SQL en
  erreur lui revient avec le message et la liste des tables utilisables : il corrige et recommence.
- **Appel au worker** (`app/graph/services/tabular_worker.py`) : `send_task` par nom vers `SQL_QUEUE_NAME`, puis
  interrogation de l'état - pas de `get()` bloquant ; l'annulation du run (#326) est regardée entre deux regards. Un worker
  qui ne répond pas en `TABULAR_QUERY_TIMEOUT_SECONDS` fait échouer la tâche avec un message clair.
- **Preuve** : une seule, dans la forme historique (SQL, résultat en tableau Markdown, sources), qui porte **tous** les
  appels de la boucle, y compris ceux en erreur ; chaque autre fichier lu est une source citable à part.
- **Graphiques** (#434) : `{"action": "create_chart", "query": N, "chart": {...}}` dessine le résultat de la requête N. Le worker
  rejoue la requête et rend le PNG ; l'agent le confie au backend (`POST /api/internal/runs/{id}/charts`), qui rend le
  Markdown de l'image (`![titre](/api/conversations/{c}/charts/{g}.png)`), mis dans la preuve. Six au plus par réponse. Un
  graphique que le modèle n'a pas écrit dans sa réponse est **ajouté à la fin** (`with_missing_charts`).
- `app/agent/tabular_contracts.py` est une **copie** de `worker/tabular/app/contracts.py` : un test échoue si elles divergent.

## Les sources d'une réponse (#402)

Une affirmation est rattachée à sa source par un marqueur `[id de l'extrait]` dans la réponse, et le chat construit ses
sources à partir de ces seuls marqueurs. Rien ne garantissait que le modèle les écrive (`app/graph/services/citations.py`) :

- **La consigne de citation est dans le code**, ajoutée au prompt système après le prompt administrable (`get_prompt`) :
  une version surchargée ne la perd plus.
- **Contrôle après génération, en code** : les ids qui ne sont pas un extrait fourni sont retirés de la réponse ; si elle ne
  cite plus rien alors qu'il y avait de l'évidence, elle est **gardée telle quelle** (le chat indique qu'elle n'a pas de
  source) : un second appel coûterait autant que le premier pour une réponse souvent identique.
- **Sortie structurée** : le modèle rend `{"answer": "…", "sources": [{"id", "quote"}]}`, `answer` d'abord pour que le chat
  l'affiche pendant l'écriture (`partial_answer` lit le champ au fil du flux). Le worker ne garde **jamais** la copie du
  modèle : il cherche `quote` dans l'extrait désigné par l'`id` (insensible à la casse, aux espaces, aux retours à la
  ligne, aux guillemets typographiques et aux césures) et garde **le texte de l'extrait lui-même**, avec sa position
  (`quote`, `quote_start`, `quote_end` dans chaque citation). Une citation dont le passage n'est pas dans l'extrait est
  **gardée sans passage** ; un `id` inconnu est écarté. Un modèle qui n'écrit pas ce JSON a tout son texte pris pour la
  réponse, avec les seuls marqueurs `[id]` (comportement d'avant).
- Chaque citation renvoyée porte `cited` : l'extrait est cité par la réponse, ou seulement consulté. Le chat montre les
  premiers.
- Une réponse qui ne cite toujours rien est gardée, et le chat l'indique (« Sans source : vérifiez-la avant de vous y
  fier ») ; une réponse sans évidence le dit elle-même.
- Un extrait sans nom de source est présenté au modèle sous le nom de son outil, plus sous `None`.

### Le contrôle d'ancrage (`ground_check`)

Un appel au modèle **après** la génération, une fois le run terminé : la réponse est partie, l'utilisateur ne l'attend pas, et le
verdict est enregistré sur le run (`grounding_valid`, `grounding_unsupported_claims`). Il n'est fait que pour une réponse
difficile à écrire (plusieurs requêtes, ou complexité forte) ; une recherche simple ou un outil n'en ont pas. Il lit chaque extrait
**en entier jusqu'à 2 000 caractères** (et, pour un extrait plus long, autour du passage cité), avec le passage cité signalé. Il rend
trois listes, plus une quatrième trouvée sans modèle :

| Liste | Sens |
|---|---|
| `unsupported_claims` | affirmation que rien ne soutient |
| `miscited_claims` | cite un extrait qui ne la soutient pas (`supported_by` : celui qui la soutient) |
| `uncited_claims` | soutenue par les extraits mais sans citation |
| `unverified_citations` | citation dont le passage n'est pas dans l'extrait (trouvée sans modèle) |

Il ne relance ni recherche ni réécriture : un verdict est un constat, pas une boucle. La consigne de contrôle des citations est dans
le code, comme celle de la génération : un prompt `validate_grounding` surchargé la garde.
