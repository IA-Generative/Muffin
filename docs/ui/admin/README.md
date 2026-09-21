# Page Administration (`/admin`)

Documente la page `/admin` du frontend telle qu'elle existe aujourd'hui, pour servir de
référence à un agent capable d'interagir avec l'UI (navigation, remplissage de formulaires,
lecture d'état). Ce dossier `docs/ui/` suit la logique des pages de l'application : un
sous-dossier par page/écran, chacun avec son propre `README.md` + captures d'écran.

Composant Vue : [`frontend/src/components/AdminSettingsView.vue`](../../../frontend/src/components/AdminSettingsView.vue).
Route : `/admin` (voir [`frontend/src/router/index.ts`](../../../frontend/src/router/index.ts)).

## Accès

- **Admin uniquement.** Le lien "Administration" n'apparaît dans le menu utilisateur (sidebar,
  clic sur le bloc nom/email en bas à gauche) que si `user.isAdmin` est vrai
  (voir [`frontend/src/components/ChatSidebar.vue`](../../../frontend/src/components/ChatSidebar.vue),
  bouton `role="menuitem"` avec le texte "Administration").
- Naviguer directement vers `/admin` sans être connecté affiche quand même le squelette de la
  page, mais chaque section échoue avec un message d'erreur rouge ("Impossible de récupérer...")
  car les appels API renvoient 401/403.
- En dev, l'utilisateur seedé admin dans Keycloak (`docker/keycloak/realm-muffin.json`) est
  `michou` / `muffin-dev`.
- **Piège pour un agent qui pilote l'UI** : `useChat.ts::initializeConversations()` redirige
  automatiquement vers la conversation la plus récente dès qu'une session démarre avec
  `activeId === 'default'` (typiquement juste après un login), **sans regarder la route
  courante**. Un chargement direct de `/admin` (ou un `goto` complet) juste après
  l'authentification peut donc être arraché vers `/c/<id>` une seconde ou deux plus tard. Pour
  atteindre `/admin` de façon fiable : laisser cette redirection se produire une première fois
  (ouvrir `/`, attendre), puis naviguer vers `/admin` en JS côté client (clic sur le lien du
  menu, ou `router.push`) plutôt que par un rechargement complet de page. C'est un bug
  préexistant, non corrigé, indépendant du contenu de cette page.

## Structure de la page

Une seule colonne centrée (`max-width: 48rem`), scroll interne (`.admin-view`, pas le body).
Deux sections empilées : **Modèle d'embedding** puis **Prompts de l'agent**. Voir
[`screenshots/admin-overview.png`](screenshots/admin-overview.png) pour l'ensemble de la page.

### 1. Modèle d'embedding

Carte unique (`.admin-card`), formulaire.

- **Texte d'intro** : explique que ce modèle est global (pas par collection), utilisé pour
  comparer une question à la description de chaque collection.
- **Select "Modèle"** (`#admin-embedding-model`) : liste les modèles d'embedding disponibles sur
  le hub LLM. Désactivé pendant leur chargement.
  - Si aucun modèle n'a encore été choisi côté serveur, un texte d'aide précise que le premier
    modèle disponible sur le hub est utilisé par défaut.
  - Si la liste des modèles ne charge pas, un texte d'erreur s'affiche à la place.
- **Bouton "Enregistrer"** : désactivé tant que rien n'est sélectionné. Au clic, `PATCH
  /api/admin/settings/embedding-model` avec `{ "embedding_model": "<id>" }`. Un texte
  "Enregistré" apparaît brièvement (2s) à gauche du bouton en cas de succès.

Composable : [`frontend/src/composables/useAdminSettings.ts`](../../../frontend/src/composables/useAdminSettings.ts)
(`fetchAdminSettings`, `updateEmbeddingModel`) +
[`useEmbeddingModels.ts`](../../../frontend/src/composables/useEmbeddingModels.ts) pour la liste
des modèles.

API : `GET /api/admin/settings`, `PATCH /api/admin/settings/embedding-model` — backend
[`admin_settings.py`](../../../backend/app/routers/admin_settings.py).

### 2. Prompts de l'agent

Section ajoutée pour le versioning des prompts système de l'agent de recherche (issue #96,
voir [`docs/research-agent-plan.md`](../../research-agent-plan.md)). Texte d'intro : publier une
version prend effet sans redéploiement du worker (cache rafraîchi côté worker dans la minute),
et l'historique permet un rollback à tout moment.

En dessous, une carte [`PromptEditor.vue`](../../../frontend/src/components/PromptEditor.vue)
**par prompt** existant. Aujourd'hui il y en a 6, dans cet ordre (déterminé par le tri
alphabétique du backend) :

1. `analyze_query`
2. `decompose_query`
3. `evaluate_coverage`
4. `generate_answer`
5. `replan_research`
6. `validate_grounding`

Ce sont les prompts système des nodes du graphe LangGraph de l'agent
(`worker/agent_execution/app/graph/nodes/*.py`). Le nom affiché en haut de chaque carte
(police monospace) est directement le nom technique utilisé comme clé API — pas de libellé
humain séparé.

#### Anatomie d'une carte prompt

Voir [`screenshots/admin-overview.png`](screenshots/admin-overview.png) (état replié, les 6
cartes) et [`screenshots/prompt-history-expanded.png`](screenshots/prompt-history-expanded.png)
(une carte avec historique déplié).

- **En-tête** : nom du prompt + badge. Badge bleu-vert "v`N` active" si une version est active,
  badge gris "Aucune version active" sinon (ne devrait pas arriver en pratique : la migration
  Alembic seed les 6 prompts en v1 active dès l'installation).
- **Textarea** (`.prompt-editor__textarea`) : pré-remplie avec le contenu de la version active
  au chargement (`watch` sur `activeVersion`). Éditable librement, redimensionnable
  verticalement. Voir [`screenshots/prompt-editing-draft.png`](screenshots/prompt-editing-draft.png)
  pour l'état "brouillon modifié".
- **Bouton "Voir l'historique" / "Masquer l'historique"** : toggle. À l'ouverture, appelle `GET
  /api/admin/prompts/{name}/versions` (une fois par prompt, mise en cache côté composable —
  rouvrir ne refetch pas sauf après une publication/activation).
- **Bouton "Publier cette version"** : désactivé si la textarea est vide/inchangée-vide ou
  pendant la publication (`disabled="!draft.trim() || publishing"`, libellé devient
  "Publication…"). Au clic :
  1. `POST /api/admin/prompts/{name}/versions` avec `{ "content": "<texte>" }` → crée une
     nouvelle version, **non active** par défaut (numéro = max existant + 1).
  2. Le front refetch l'historique pour connaître le numéro de version qui vient d'être créé
     (c'est le premier élément, l'API trie par version décroissante).
  3. `POST /api/admin/prompts/{name}/versions/{version}/activate` sur cette version → **publier
     = créer + activer immédiatement**, il n'y a pas d'état "brouillon sauvegardé mais pas
     publié" dans l'UI actuelle.
  4. Un texte "Publié" apparaît brièvement (2s).
- **Liste d'historique** (si dépliée) : une ligne par version, plus récente en premier
  (`v{n}`, date formatée `Intl.DateTimeFormat('fr-FR', dateStyle: 'medium', timeStyle: 'short')`,
  badge "active" si c'est la version courante). Chaque version **non active** a un bouton
  "Revenir à cette version" (`disabled` + libellé "Activation…" pendant l'appel) qui appelle
  directement `POST /api/admin/prompts/{name}/versions/{version}/activate` — **c'est le
  mécanisme de rollback**, pas de confirmation demandée.

Composable : [`frontend/src/composables/usePrompts.ts`](../../../frontend/src/composables/usePrompts.ts)
(`fetchPrompts`, `fetchVersions`, `createVersion`, `activateVersion`).

API (admin, auth Keycloak + `is_admin`) — backend
[`admin_prompts.py`](../../../backend/app/routers/admin_prompts.py) :

| Méthode | Route | Usage |
|---|---|---|
| GET | `/api/admin/prompts` | Liste les prompts + leur version active (alimente les 6 cartes) |
| GET | `/api/admin/prompts/{name}/versions` | Historique complet d'un prompt, trié version desc |
| POST | `/api/admin/prompts/{name}/versions` | Crée une version (`{content}`), jamais active d'office |
| POST | `/api/admin/prompts/{name}/versions/{version}/activate` | Active cette version (publication ou rollback) |

## Ce qui n'est *pas* éditable depuis cette page

Pour `decompose_query` et `replan_research`, seule la partie "instructions" du prompt est
stockée/éditable ici. La liste des outils disponibles et l'activation conditionnelle de l'outil
`web_search` restent codées en dur côté worker (jamais exposées à l'admin, pour ne jamais
pouvoir accidentellement activer `web_search` pour un run qui n'a pas explicitement opté in) —
voir les commentaires dans `worker/agent_execution/app/graph/nodes/decompose_query.py` et
`replan_research.py`.

## États d'erreur

Chaque section a son propre `error`/`isLoading` indépendant (pas de état d'erreur global pour
toute la page) :

- Section embedding : `error` → texte rouge à la place du formulaire.
- Section prompts : `promptsError` → texte rouge, la liste des cartes ne s'affiche pas du tout.
- Un échec de `createVersion`/`activateVersion` individuel affiche `error` (composable
  `usePrompts`) mais n'est **actuellement affiché nulle part dans `PromptEditor.vue`** — le
  bouton retourne juste à son état normal sans message visible en cas d'échec réseau. À garder
  en tête si un agent doit détecter un échec de publication : il faut inspecter la réponse
  réseau elle-même, pas un message affiché.
