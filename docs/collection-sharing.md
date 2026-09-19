# Partage et visibilité des collections

Documente l'architecture mise en place par #13/#26 (visibilité `private`/`public`,
partage par email/groupe Keycloak) et surtout les **limites connues et non corrigées**,
pour qu'elles puissent être reprises plus tard sans avoir à ré-auditer tout le code.

## Architecture en bref

- `Collection.visibility` (`private` par défaut, `public`) - une collection publique est
  visible et cherchable en lecture seule par tout utilisateur authentifié.
- `CollectionShare` (partage direct par utilisateur ou par groupe Keycloak) fonctionne par
  **invitation hashée, jamais par recherche live** :
  - `POST /api/collections/{id}/shares` (`backend/app/services/collection_service.py::create_share`)
    ne fait **aucun** appel à Keycloak. Il calcule `HMAC-SHA256(identifiant normalisé, SHARE_INVITE_PEPPER)`
    (`backend/app/core/sharing.py`) et crée une ligne `CollectionShare` `status=pending`,
    `subject_id=NULL`, `invited_identifier_hash=<hash>`.
  - À chaque connexion BFF (`POST /api/auth/callback`, `backend/app/routers/auth.py::_resolve_pending_shares`),
    les invitations `pending` dont le hash correspond à l'email ou à l'un des groupes du token
    (déjà vérifiés par Keycloak) sont promues `active` avec `subject_id` résolu.
  - Aucun client Keycloak Admin, aucun service account : tout est dérivé du token déjà vérifié.
- `CollectionRepository.list_accessible`/`get_accessible`/`list_all_accessible`
  (`backend/app/repositories/collection_repository.py`) : owner OR `visibility=public` OR
  partage `active` direct OR partage `active` vers un groupe de l'utilisateur. C'est la seule
  barrière de permission, utilisée à la fois par la liste UI et par
  `GET /internal/users/{id}/accessible-collections` (routing VDB de l'agent).
- `Run.user_groups` (`backend/app/models/run.py`) : snapshot de `RequestContext.groups` pris à la
  création du run, propagé via `InternalRunOut` jusqu'à `AgentState` puis à
  `load_accessible_vdbs` (`worker/agent_execution/app/graph/nodes/load_accessible_vdbs.py`), pour
  que les collections partagées à un groupe soient effectivement cherchables par l'agent.

## Limites connues (non corrigées, par ordre de priorité suggéré)

### 1. Les endpoints de citation de l'agent restent strictement owner-only

**Fichiers** : `backend/app/routers/internal_runs.py`
- `list_collection_documents` (ligne ~190-194) : `CollectionRepository(db).get(collection_id, user_id)`
- `get_document_page` (ligne ~208-213) : `document.collection.owner_id != user_id`

Les deux utilisent le check owner-only (`CollectionRepository.get`), pas `get_accessible`.
Si l'agent trouve un chunk dans une collection publique/partagée (ce qui fonctionne, `search`
n'est pas scopé par owner), la citation détaillée (nom du document, page, screenshot) échouera
en 404 côté worker pour un utilisateur non-owner de cette collection.

**Pourquoi ça n'a pas été corrigé avec le reste** : ces deux endpoints ne reçoivent que
`user_id` en paramètre de chemin, pas les groupes - contrairement à
`GET /internal/users/{id}/accessible-collections` qui accepte déjà `groups` en query param
depuis #26. Il faudrait soit ajouter le même paramètre `groups` ici (et le faire passer par
`backend_client.list_collection_documents`/`get_document_page` côté worker, qui ont accès à
`state["user_groups"]` exactement comme `load_accessible_vdbs`), soit remplacer le check par
`CollectionRepository.get_accessible(collection_id, user_id, groups)`.

**Comment le reproduire** : partager une collection publique, poser une question dont la
réponse cite un document de cette collection avec un compte qui n'en est pas owner, ouvrir la
citation dans l'UI (`SourceDocumentModal.vue` côté frontend, `GET /internal/users/.../pages/{n}`
côté worker) - 404.

### 2. Les actions d'écriture ne sont pas gatées dans les autres onglets

**Fichiers concernés** (aucun ne vérifie `collection.isOwner`) :
- `frontend/src/components/CollectionDocumentsTab.vue` : upload de fichier (input `type="file"`
  ligne ~70-75, drag & drop ligne ~68), ajout d'URL (`addUrl`, ligne ~39), suppression de
  document (`removeDocument`, ligne ~129).
- `frontend/src/components/CollectionQaTab.vue` : formulaire d'ajout de QA (`addQaPair`, ligne
  ~21), validation/dévalidation (`toggleQaValidation`, ligne ~59), suppression (`removeQaPair`,
  ligne ~71).
- `frontend/src/components/CollectionEvaluationTab.vue` : lancement d'une évaluation
  (`runEvaluation`, ligne ~61).

`CollectionChunksTab.vue` et `CollectionRelationsTab.vue` sont déjà purement en lecture - rien à
faire dessus.

Seuls l'en-tête de collection (nom/description/tags/suppression) et l'onglet Paramètres
(`CollectionDetailView.vue`) sont gatés par `collection.isOwner` aujourd'hui.

**Pas une faille de sécurité** : le backend refuse déjà ces actions en écriture pour un
non-owner (`CollectionService._get_owned`, owner-only sur toutes les mutations). Le bouton
existe juste dans l'UI et échouera silencieusement (la plupart des fonctions de
`useCollections.ts` font `if (!response.ok) return` sans remonter d'erreur visible) au lieu de
ne pas s'afficher.

**Comment corriger** : dans chacun des trois fichiers, `defineProps<{ collection: Collection }>()`
donne déjà accès à `collection.isOwner` - entourer les boutons/formulaires concernés d'un
`v-if="collection.isOwner"`, sur le modèle de ce qui a été fait dans
`CollectionDetailView.vue` (voir le diff de #26 pour le pattern exact : `v-if` sur l'élément,
jamais de `disabled` seul qui laisserait le bouton visible).

### 3. Pas de rate-limiting sur `POST /api/collections/{id}/shares`

**Fichier** : `backend/app/routers/collections.py::create_share`

Rien n'empêche un owner de créer un grand nombre d'invitations `pending` sur sa propre
collection (spam de la table `collection_shares`). Ce n'est plus un risque de fuite d'info
(il n'y a plus de lookup Keycloak à confirmer/infirmer), juste un risque de volumétrie/abus.

**Comment corriger** : réutiliser `SessionStore.check_rate_limit` (déjà utilisé par
`/api/auth/login`, voir `backend/app/routers/auth.py::LOGIN_RATE_LIMIT`) sur une clé du type
`f"share:{user.user_id}"`.

### 4. Pas de sélecteur de groupe dans l'UI

**Fichier** : `frontend/src/components/CollectionSettingsTab.vue` (section "Partages")

L'owner doit taper le chemin exact du groupe Keycloak (`/muffin-dev-team`) à la main - aucune
liste, aucune autocomplétion. C'est un choix assumé (voir la discussion qui a mené à #26) pour
ne jamais faire de recherche live côté Keycloak, mais reste ergonomiquement rugueux.

**Piste si on veut l'améliorer sans réintroduire de lookup live** : miroir local des groupes
"vus" passivement à la connexion (comme `RequestContext.groups` l'est déjà), matérialisé dans
une table `keycloak_groups (id, name)` alimentée à chaque login - le sélecteur ne listerait
que les groupes déjà rencontrés, pas les groupes flambant neufs sans membre connecté depuis le
déploiement. Cette option avait été évaluée puis écartée au profit de la saisie libre - voir
l'historique de la conversation ayant produit #26 pour le détail du compromis.

### 5. Pas de test end-to-end navigateur automatisé dans le repo

La vérification de #26 (login réel, création/partage/passage en public, résolution au login
suivant) a été faite via un script Playwright ponctuel (`frontend/scripts/_tmp_verify_sharing*.mjs`),
jamais committé. Si une régression UI survient sur ce flow, rien ne la détecte en CI.

**Comment corriger** : industrialiser ce script en test Playwright réel dans le repo (le projet
a déjà `@playwright/test` en dépendance frontend, voir `frontend/scripts/screenshot.mjs`), ou au
minimum documenter le scénario de test manuel dans ce fichier.

### 6. Autres points mineurs, non bloquants

- `GET /api/collections/{id}/shares` n'est pas paginé - non problématique tant qu'une collection
  n'accumule pas des centaines de partages.
- La perte ou la rotation de `SHARE_INVITE_PEPPER` invalide silencieusement toutes les
  invitations `pending` non encore résolues (déjà documenté dans
  `docs/environment-variables.md`, rappelé ici car c'est le genre de piège qui mérite d'être
  connu avant un premier déploiement en prod).
- Un partage révoqué (`DELETE .../shares/{id}`) retire l'accès immédiatement côté backend, mais
  un onglet déjà ouvert ailleurs dans le navigateur (state Vue en mémoire) ne le saura qu'au
  prochain `refresh`/`openCollection` - pas de push temps réel.
