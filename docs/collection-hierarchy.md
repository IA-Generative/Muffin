# Sous-collections

Documente la hiérarchie de collections mise en place par l'épique #213 : une collection peut
contenir des sous-collections, sur autant de niveaux que nécessaire, comme des dossiers. Chaque
sous-collection reste une collection à part entière (documents, index Qdrant, paramètres).

Côté interface, voir [docs/ui/collections/README.md](ui/collections/README.md#sous-collections-213).

## Modèle de données (#214)

- `Collection.parent_id` (nullable, `ON DELETE CASCADE`) : `NULL` pour une collection de premier
  niveau. Pas de relation ORM `children`, pour que l'ORM ne charge jamais un sous-arbre entier.
- Un parent peut avoir ses propres documents en plus de ses sous-collections.
- Contraintes en base :
  - `ck_collections_not_own_parent` : une collection n'est pas son propre parent ;
  - `ck_collections_temporary_has_no_parent` : une collection temporaire (fichiers d'une
    conversation, « Fichiers à ranger ») n'a pas de parent.
- Règles vérifiées par `CollectionHierarchyService.set_parent`
  (`backend/app/services/collection_hierarchy_service.py`), qui lève une `HierarchyError` :
  - pas de cycle (une collection ne va ni sous elle-même ni sous une de ses descendantes) ;
  - même propriétaire que le parent ;
  - jamais de collection temporaire, ni comme enfant ni comme parent.
- Supprimer une collection supprime tout son sous-arbre. `CollectionService.delete_collection`
  nettoie RustFS et Qdrant pour chaque descendant.
- Parcours de l'arbre : `CollectionHierarchyRepository`
  (`backend/app/repositories/collection_hierarchy_repository.py`), par CTE récursives. Chacune se
  protège d'un cycle : `UNION` quand les lignes sont de simples ids, liste des ids déjà visités
  quand elles portent une profondeur.

## API (#215)

| Route | Rôle |
|---|---|
| `POST /api/collections` avec `parent_id` | Crée une sous-collection d'une collection que l'on possède. Elle part d'une **copie** des paramètres du parent (chunking, embedding, instructions, modèles, fenêtres). |
| `PATCH /api/collections/{id}` avec `parent_id` | Déplace la collection ; `null` la remet au premier niveau, champ absent = inchangé. Une règle violée n'applique aucun autre champ. |
| `GET /api/collections` | À plat sur tous les niveaux ; `?roots_only=true` pour le premier niveau seulement. |
| `GET /api/collections/{id}/children` | Sous-collections directes, paginées. |

Erreurs : parent introuvable ou non possédé → 404 `Parent collection not found` ; cycle ou
collection temporaire → 409.

`CollectionOut` porte `parent_id`, `path` (de la racine au parent) et `children_count`, **relatifs
à ce que l'appelant peut lire** : `path` s'arrête au premier ancêtre illisible, et `parent_id`
vaut `null` si le parent l'est. Une collection partagée seule ne révèle donc jamais l'arbre
au-dessus d'elle.

## Droits hérités (#216)

Une collection est lisible si elle l'est directement (propriétaire, publique, partage actif
utilisateur ou groupe) **ou si l'un de ses ancêtres l'est**. Les droits descendent, jamais vers le
haut ni vers les collections sœurs. L'écriture reste réservée au propriétaire.

- C'est `CollectionRepository._accessible_where`, la barrière unique utilisée par l'UI, l'agent,
  l'évaluation et les droits d'édition. Deux sens de parcours :
  - les listings descendent depuis toutes les collections accordées directement ;
  - les vérifications sur des ids connus (`get_accessible`, `filter_accessible_ids`) remontent
    depuis ces ids.
- `CollectionOut.inherited_public_from` : l'ancêtre public le plus proche d'une collection privée,
  qui est donc lisible par tous.
- `GET /collections/{id}/shares` liste aussi les partages hérités des ancêtres, avec
  `inherited_from`. Ils ne se révoquent que sur l'ancêtre.
- Mesures (21 200 collections) : une vérification sur une collection prend environ 4 ms, et un
  listing environ 65 ms, dont la moitié de JIT Postgres. Détail dans #216.

Rendre un enfant plus privé que son parent n'est pas prévu.

Voir aussi [docs/collection-sharing.md](collection-sharing.md) pour le partage lui-même.

## Description d'un parent (#218)

La description d'une collection est générée à partir des résumés de ses documents. Celle d'un
parent est recalculée à partir de ses documents propres **et** des descriptions de ses
sous-collections directes : la tâche `rollup_collection_description` du worker
`document_process`.

- Le backend la programme (`DescriptionRollupService`) dans ces cas :
  - la description d'une sous-collection change, par le pipeline ou à la main ;
  - une sous-collection décrite est déplacée (ancien et nouveau parent) ;
  - une sous-collection décrite est supprimée.
- **Regroupement sur 60 s** : un verrou Redis fait qu'un seul recalcul par parent et par minute
  absorbe tous les changements de la fenêtre.
- Une description réellement modifiée passe par la route interne habituelle, ce qui programme le
  niveau du dessus. Une description inchangée arrête la propagation.
- Pas de paires Q/R de collection générées à cette occasion, faute de document déclencheur.

## Recherche (#217)

Les routes internes `/api/internal/search`, `/qa-search` et `/summary-search` acceptent
`include_descendants` (faux par défaut) pour chercher aussi dans tout le sous-arbre. Une recherche
ne s'élargit jamais d'elle-même : chaque sous-collection ajoute une requête d'index. Chaque
résultat porte `collection_path`, limité aux collections demandées.

## Agent (#219, #233)

**Routage à plat** (`worker/agent_execution/app/graph/services/vdb_router.py`) : toutes les
collections accessibles, tous niveaux confondus, sont en concurrence sur leur description.

- Jusqu'à 20 collections, l'IA les voit toutes ; au-delà, une recherche vectorielle sur les
  descriptions garde les 20 plus proches.
- Un seul appel IA choisit. Les collections imbriquées sont présentées avec leur chemin
  (« RH › Congés »), sans jamais nommer un ancêtre illisible.
- Avec des sous-collections, au plus `MAX_ROUTED_COLLECTIONS` (15) sont interrogées. Sans
  sous-collections, le routage est celui d'avant.

**Aller plus loin**
- Le point d'arrêt d'une réponse regroupe les collections retenues dont des sous-collections n'ont
  jamais été présentées à l'IA, plus l'ancêtre retenu le plus proche de celles coupées par le
  plafond. Il est stocké sur `Run.unexplored_collection_ids` et la réponse le signale.
- Un message envoyé avec `continue_exploration` (bouton « Aller plus loin ») reprend depuis le
  point d'arrêt de la réponse précédente de la conversation, limité à leurs sous-collections, et
  toujours recroisé avec les collections accessibles.

**Épingles (#220)**
- Épingler une collection dans le chat épingle aussi ses sous-collections, à la création du run
  (`include_descendants`, vrai par défaut).
- Seules les `PINNED_DESCENDANTS_LIMIT` (30) plus proches sont épinglées. La collection épinglée la
  plus proche de chaque collection laissée de côté devient un point d'arrêt du run.
- Les citations portent `vdb_path`, le chemin de leur collection.

## Import d'un ZIP (#223)

Un ZIP uploadé crée une collection à son nom (suffixé « (2) » si le nom est déjà pris au même
niveau) : ses dossiers deviennent des sous-collections et ses fichiers des documents.

- **Où** : déposé dans l'onglet Documents d'une collection, il va juste en dessous. Déposé dans une
  conversation ou sur « Fichiers à ranger », il va au premier niveau. Depuis une conversation, ses
  runs l'épinglent avec ses sous-collections, et il reste si la conversation est supprimée.
- **Comment** : le backend (`POST /api/collection-imports`) stocke l'archive dans RustFS et crée
  la collection racine ; la tâche `import_zip` du worker `document_process` lit l'archive et crée
  le reste par l'API interne. Les règles de sécurité (Zip Slip, zip bomb, liens symboliques,
  fichiers cachés, types non pris en charge...) sont dans `worker/document_process/app/zip_import.py`
  ; ce qui est écarté est listé dans le récapitulatif de l'import.
- **Suggestion de rattachement** : pour un ZIP déposé sans emplacement, la description de sa
  collection est comparée à celles des collections de l'utilisateur dès que le pipeline l'a
  produite, et les 3 plus proches sont proposées (accepter, choisir une autre, ignorer), comme le
  rangement des fichiers (#122).

## Variables d'environnement

| Variable | Service | Défaut |
|---|---|---|
| `MAX_ROUTED_COLLECTIONS` | worker `agent_execution` | `15` |
| `PINNED_DESCENDANTS_LIMIT` | backend | `30` |
| `ZIP_IMPORT_MAX_FILES`, `ZIP_IMPORT_MAX_TOTAL_BYTES`, `ZIP_IMPORT_MAX_FILE_BYTES`, `ZIP_IMPORT_MAX_RATIO`, `ZIP_IMPORT_MAX_DEPTH` | worker `document_process` | aucune limite, sauf le taux de compression (100) |

Détail dans [docs/environment-variables.md](environment-variables.md).

## Limites connues

- Le front charge les collections en une page de 100 et en déduit l'arbre côté client (liste,
  sélecteur du chat, fenêtre « Déplacer »). Au-delà, l'onglet « Sous-collections » reste correct
  (il interroge `/children`), mais le reste ne voit que les 100 premières.
- La description indexée d'une sous-collection ne contient pas son chemin. Une description courte
  (« Rapports 2024 ») peut donc manquer de contexte pour la recherche vectorielle du routage ;
  l'IA, elle, voit le chemin.
- Pas de glisser-déposer pour déplacer une collection.
