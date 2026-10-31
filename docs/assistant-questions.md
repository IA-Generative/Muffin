# Questions à choix posées par l'assistant (#344)

Quand une demande est ambiguë, l'assistant ne devine pas : il pose 1 à 4 questions, chacune avec 2 à 4 options (libellé et
description courte), à choix unique ou multiple, et l'utilisateur répond en un clic - ou en texte libre.

## Cycle de vie : l'historique est l'état

Rien n'attend la réponse. Une question n'est pas une pause du graphe mais la fin d'un run :

1. `analyze_query` juge la demande ambiguë et propose des `questions`. Le nœud `request_clarification` les nettoie
   (`backend/app/agent/ask_user.py`), met leur texte en réponse du run, et le run se termine (`completed`).
2. Le backend enregistre les questions avec le message de l'assistant (`messages.questions`, la même chose en texte dans
   `content`). L'interface les affiche en carte.
3. L'utilisateur répond quand il veut, même des jours plus tard : sa réponse est un **nouveau message** (`POST /api/runs`
   avec `answers_run_id` - le run qui a posé les questions - et `answers`, une réponse par question). Le backend garde la
   réponse sur le message des questions (`messages.questions_answer`) et reprend les collections et le choix de recherche web
   du run qui avait posé la question. Le texte du message (`query`) est la réponse mise en forme, celle que dit le fil.
4. `analyze_query` lit la conversation : questions de l'assistant, puis réponse. Il réécrit la demande d'origine en y
   incluant les réponses (`standalone_query`) et ne la juge plus ambiguë.

Si l'utilisateur écrit autre chose au lieu de répondre, les questions sont **abandonnées** (`questions_abandoned`, calculé
à la lecture du fil : des questions sans réponse qui ne sont plus le dernier message). Elles ne peuvent plus être répondues
(409). Une réponse invalide (option non proposée, plusieurs options pour une question à choix unique, question sans réponse)
est refusée (422).

## Ce que le modèle propose, et ce qu'on en garde

`ask_user.py` : les textes sont bornés (question 300 caractères, en-tête 12, libellé 60, description 120), les espaces
normalisés, les options dédoublonnées et plafonnées à 4, 4 questions au plus. Une question de moins de 2 options utilisables est
écartée. Sans question valable, le nœud retombe sur la question de clarification en texte libre (`clarification_question`),
affichée sans options - comme avant. `ASK_USER_TOOL` est la définition de l'outil `ask_user` (arguments, et description qui
dit de ne l'utiliser que si la précision change vraiment le résultat) : la boucle d'outils du chat (#343) l'exposera au modèle, avec le
même nettoyage. La consigne est ajoutée à la fin du prompt d'`analyze_query`, quelle que soit sa version administrée.

## Garde-fous

- **Plafond** : après `MAX_QUESTION_ROUNDS` (2) tours de questions de suite, l'assistant poursuit avec des hypothèses, qu'il
  énonce en début de réponse.
- **Personne à interroger** : un run non interactif (`Run.interactive = false`, `RunCreate.interactive`) ne pose jamais de
  question : il poursuit avec des hypothèses énoncées, comme ci-dessus. C'est le cas à prévoir pour les runs lancés par MCP ou A2A
  (#21, #29), qui n'existent pas encore dans ce dépôt.

## Événements

`clarification_requested` (avec `question`, le texte, et `questions`, la forme structurée) est émis quand le run se termine sur des
questions ; `clarification_received` (`answer`) quand le run suivant démarre sur une réponse. Les clients du flux d'événements
n'ont rien à changer.

L'ancienne reprise (`POST /api/runs/{id}/resume`, tâche `resume_agent`) reste pour un run qui attendait déjà une réponse
au déploiement ; plus rien ne met un run en `waiting_for_user`.

## Interface

`ChatQuestions.vue` : un onglet par question (l'en-tête) quand il y en a plusieurs, les options avec leur description (cases
pour le choix multiple, boutons radio sinon), un champ de texte libre toujours disponible, un bouton « Envoyer mes réponses » actif
quand chaque question a une réponse. Clavier : les flèches, Début et Fin parcourent les onglets ; les champs sont des
`fieldset`/`legend` DSFR, l'état « répondu » d'un onglet est dit aux lecteurs d'écran. Une fois répondue ou abandonnée, la carte
reste dans l'historique, en lecture seule, avec la réponse donnée.
