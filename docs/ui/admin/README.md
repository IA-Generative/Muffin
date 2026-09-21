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
[`screenshots/prompt-carousel-overview.png`](screenshots/prompt-carousel-overview.png) pour
l'ensemble de la page.

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

En dessous, un **carrousel** : une seule carte [`PromptEditor.vue`](../../../frontend/src/components/PromptEditor.vue)
visible à la fois, une par prompt existant. Aujourd'hui il y en a 6, dans cet ordre (déterminé
par le tri alphabétique du backend) :

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

#### Le carrousel

Au-dessus de la carte : flèche précédente (`aria-label="Prompt précédent"`), une rangée de
points cliquables (un par prompt, `aria-current` sur celui affiché), flèche suivante
(`aria-label="Prompt suivant"`), puis un compteur texte `N / 6`. Naviguer change la carte
affichée (`AdminSettingsView.vue::promptIndex`) - la carte est démontée/remontée à chaque
changement (`:key="prompts[promptIndex].name"`), donc **son état interne (brouillon en cours,
version sélectionnée) ne survit pas au changement de carte**, elle repart toujours sur la
version active. Voir [`screenshots/prompt-carousel-second-card.png`](screenshots/prompt-carousel-second-card.png)
(carte 2/6, `decompose_query`, fraîche).

#### Anatomie d'une carte prompt

Voir [`screenshots/prompt-carousel-overview.png`](screenshots/prompt-carousel-overview.png)
(carte en mode édition, version active) et
[`screenshots/prompt-past-version-readonly.png`](screenshots/prompt-past-version-readonly.png)
(une version passée sélectionnée, lecture seule).

- **En-tête** : nom du prompt + badge "v`N` active" (badge gris "Aucune version active" si
  aucune - ne devrait pas arriver, la migration Alembic seed les 6 prompts en v1 active), et à
  droite un **sélecteur de version** (`<select>`). Ses options : "Actuelle (éditable) - v`N`" en
  premier, puis chaque version passée (`v{n} - <date>`), triées version décroissante. **Les
  versions passées ne sont jamais modifiables** - éditer crée toujours une nouvelle version, il
  n'y a pas de "modifier v2 en place".
- Sélectionner "Actuelle" (ou au premier chargement) → **mode édition** :
  - **Textarea** pré-remplie avec le contenu de la version active, éditable, redimensionnable.
  - **Bouton "Publier cette version"** : désactivé si la textarea est vide ou pendant la
    publication (libellé devient "Publication…"). Au clic :
    1. `POST /api/admin/prompts/{name}/versions` avec `{ "content": "<texte>" }` → crée une
       nouvelle version, non active par défaut (numéro = max existant + 1).
    2. Le front refetch l'historique du prompt pour connaître ce numéro (premier élément, trié
       version décroissante).
    3. `POST /api/admin/prompts/{name}/versions/{version}/activate` sur cette version → **publier
       = créer + activer immédiatement**, pas d'état "brouillon sauvegardé mais pas publié".
    4. Refetch à nouveau (pour que le badge/sélecteur reflètent tout de suite le nouveau
       numéro actif), puis un texte "Publié" apparaît brièvement (2s).
- Sélectionner une version passée dans le menu → **mode lecture seule** :
  - Un bandeau bleu rappelle que la version est passée, en lecture seule, et qu'il faut revenir
    à la version actuelle pour éditer (ou l'activer pour en faire la nouvelle version courante).
  - La textarea devient `readonly` (grisée), affiche le contenu figé de cette version.
  - Le bouton "Publier" est remplacé par **"Revenir à cette version"** (`disabled` + libellé
    "Activation…" pendant l'appel), qui appelle `POST
    /api/admin/prompts/{name}/versions/{version}/activate` — **c'est le mécanisme de rollback**,
    aucune confirmation demandée. Après succès, la carte revient automatiquement en mode édition
    sur la nouvelle version active.

L'historique complet d'un prompt est chargé dès le montage de sa carte (`onMounted ⇒
fetchVersions`), pas seulement à l'ouverture d'un historique déplié - nécessaire pour peupler le
`<select>` dès l'affichage.

Composable : [`frontend/src/composables/usePrompts.ts`](../../../frontend/src/composables/usePrompts.ts)
(`fetchPrompts`, `fetchVersions`, `createVersion`, `activateVersion`).

API (admin, auth Keycloak + `is_admin`) — backend
[`admin_prompts.py`](../../../backend/app/routers/admin_prompts.py) :

| Méthode | Route | Usage |
|---|---|---|
| GET | `/api/admin/prompts` | Liste les prompts + leur version active (alimente le carrousel et ses points) |
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
