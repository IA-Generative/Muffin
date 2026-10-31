# Audit : des collections lues sur place, puis reprises par le processus de Muffin

Périmètre : #453 (synchro), #454 (écriture partagée), #455 (groupes), #457 (résumés et description), branche `feat/457-resumes-owui`.
Méthode : lecture du code (fonctions et fichiers cités). Rien de ce qui suit n'a été rejoué sur la pile réelle, sauf mention « vérifié en réel ».

## Le scénario visé

- Muffin et Open WebUI **partagent le même Qdrant et le même S3, durablement**. Rien n'est déplacé : les fichiers restent où Open WebUI les a écrits, ses collections Qdrant restent telles quelles.
- Les collections copiées sont **interrogées dans Muffin telles quelles** (c'est le cas aujourd'hui, en dense seul sur le vecteur d'Open WebUI).
- Le jour où on peut **réindexer**, une collection garde son identité dans Muffin (même id, même nom, mêmes partages, mêmes documents) et **bascule sur le processus de Muffin** : index à elle, recherche hybride, puis ingestion, suppression, réindexation comme pour n'importe quelle autre. Open WebUI n'est alors plus utilisé pour cette collection.

## Réponses courtes

1. **La synchro est isolée côté exécution, pas côté données.** Worker, file, routes internes et déploiement sont séparés, et Muffin fonctionne sans eux. Mais une copie est, pour le reste du backend, une collection ordinaire sur laquelle un utilisateur peut écrire, et la synchro défait ensuite ce qu'il a fait (§2).
2. **Le partage du Qdrant et du S3 simplifie le scénario** : pas de copie de fichiers, pas de nettoyage obligatoire (§4). **Mais autoriser la réindexation ne suffit pas** : tant qu'une collection est marquée copiée, la recherche lit le Qdrant d'Open WebUI et ignore l'index que la réindexation construit. Il faut qu'**une réindexation réussie fasse basculer la collection** et que la synchro la laisse alors tranquille (§3).

## 1. Ce qui est réellement isolé

| Point | État | Preuve |
|---|---|---|
| Processus | Worker, image, file (`owui_sync`) et CronJob/KEDA propres. Inactif tant qu'aucune clé n'est donnée (CronJob suspendu, KEDA à 0). | `worker/owui_sync`, `helm/templates/worker_owui_sync` |
| Sens des appels | Le backend n'appelle jamais Open WebUI. | `worker/owui_sync/app/owui_client.py` |
| Écriture dans Muffin | Uniquement par `/internal/synced-*` (clé worker), qui refusent `source = muffin`. | `routers/internal_*_sync.py` |
| Données | `source` (défaut `muffin`) et `external_id` nullable sur groupes, collections et documents ; index uniques partiels. | modèles, migration `f2b5c8d1e3a7` |
| S3 | Objets d'Open WebUI lus sur place (`s3://bucket/clé`), jamais supprimés par Muffin. | `core/storage.py` (`is_foreign`) |
| Qdrant | Collections d'Open WebUI lues sur place, jamais écrites ; un échec renvoie `[]` sans faire échouer les autres. | `vector_store.search_external` |
| Suppressions | La clôture ne supprime que ce qui porte un `external_id` de la source, jamais rien si Open WebUI ne liste plus aucun objet d'un type. | `finish_sync` |
| Réindexation | Refusée (409) sur une copie ; `reindex_required` forcé à faux. | `IndexRebuildService.start` |

Code partagé touché : la branche `search_external` de `SearchService.search`, `is_foreign` dans le stockage, `get_current_user` (groupes de Muffin) et le droit d'écriture sur les partages. Les deux derniers sont des fonctionnalités de Muffin, indépendantes d'Open WebUI.

## 2. Là où l'isolation fuit : les écritures sur une copie

Une copie a pour propriétaire celui d'Open WebUI (son `sub` Keycloak) et, depuis #454, des droits d'écriture copiés. Les services de contenu ne regardent pas `source` (`_get_owned_collection` ne contrôle que propriété et droit d'écriture), et `CollectionOut` n'expose pas `source` : l'interface ne peut rien griser.

| Action dans Muffin sur une copie | Effet | Conséquence |
|---|---|---|
| Téléverser un fichier ou une URL | Document natif indexé dans `chunks_<id>` | Ses chunks sont **invisibles** à la recherche (elle ne lit que le Qdrant d'Open WebUI) ; seuls QA et résumés le trouvent. Supprimé en cascade si la knowledge base disparaît d'Open WebUI. |
| Supprimer un document copié | Lignes supprimées, objet S3 conservé | Recréé à la synchro suivante. |
| Retraiter un document copié | Pages, chunks et dérivés recréés | La synchro suivante remet la page unique et supprime les chunks qui ne sont pas ceux d'Open WebUI. |
| Renommer, changer le propriétaire, partager | Écrasé à chaque passe ; les partages absents d'Open WebUI sont supprimés | Perte silencieuse. |
| Changer le modèle d'embedding | Réécrit à chaque passe | Idem. |
| Supprimer la collection | Supprimée | Recréée à la passe suivante. |

Deux critères désignent « copiée » : la recherche teste `external_id IS NOT NULL` (`get_external_ids`), la réindexation teste `source != muffin`. Ils coïncident aujourd'hui, rien ne l'impose.

## 3. Pourquoi lever seulement le 409 ne suffit pas

Si on retire la garde de `IndexRebuildService.start` :

1. La reconstruction marche : le plan prend dans Postgres les chunks (ceux d'Open WebUI, avec les ids de ses points), les résumés et les QA, les embedde avec le modèle de la collection, les écrit dans `chunks_<id>` et bascule l'alias.
2. **La recherche ne bascule pas** : tant que `external_id` est renseigné, elle lit le Qdrant d'Open WebUI. Le nouvel index n'est jamais interrogé.
3. **La synchro se bat contre elle** : elle réécrit `embedding_model` à chaque passe et remplace les chunks pendant la construction.
4. Un détachement à la main (`external_id = NULL`) fait **recréer une copie** à la passe suivante tant que la knowledge base existe dans Open WebUI.

**Pourquoi l'index d'Open WebUI ne peut pas devenir celui de Muffin sur place**, même avec le même Qdrant : sa collection `open-webui_<kb>` a un vecteur dense **sans nom** et un payload `{text, metadata}`, alors que celle de Muffin a des vecteurs nommés `dense` et `sparse` (BM25) et un payload `{kind, collection_id, text, model}`. La reconstruction crée donc une collection physique de plus (`chunks_<id>_a`, derrière l'alias `chunks_<id>`) à côté de celle d'Open WebUI, sans la toucher. Les ids de points sont les mêmes (les chunks gardent l'id de leur point d'Open WebUI), et la collection de Muffin reste la même (id, nom, partages, documents).

La bascule est donc : **réindexation lancée → la copie est marquée en cours d'adoption (la synchro ne la touche plus) → reconstruction → à l'échange de l'alias, la recherche passe sur `chunks_<id>` → la copie est une collection de Muffin.** Annuler avant l'échange lève la marque.

## 4. Ce qui manque

Légende : **B** = bloquant pour le scénario, **C** = confort ou qualité, **S** = sécurité du changement.

| # | Manque | Pourquoi | Où | |
|---|---|---|---|---|
| 1 | **Un seul prédicat « copiée »**, qui devient faux pour une collection adoptée (marque `adopted_at`, ou équivalent), utilisé par la recherche, la réindexation, la synchro et l'API | Aujourd'hui deux critères, et `external_id` sert à la fois d'identité et de bascule. On le garde comme mémoire de l'origine | `collection_repository.get_external_ids`, `index_rebuild_service.start`, `search_service.search` | B |
| 2 | **Autoriser la réindexation d'une copie**, et poser la marque « adoption en cours » au démarrage | C'est la demande. La marque protège la construction contre la synchro | `IndexRebuildService.start`, `routers/index_rebuilds.py` | B |
| 3 | **La synchro laisse une collection en adoption ou adoptée** : ni nom, partages, modèle, pages, chunks réécrits, ni suppression, ni recréation | Sinon écrasement ou doublon | `CollectionSyncRepository.sync`, `DocumentSyncRepository.sync`, `finish_sync` | B |
| 4 | **Bascule de la recherche à l'échange de l'alias**, pas avant | Avant l'échange `chunks_<id>` ne contient que les résumés : basculer plus tôt, c'est perdre les chunks | `SearchService.search`, `IndexRebuildService.swap` | B |
| 5 | **Fichiers qui restent dans le préfixe d'Open WebUI** : décider de la suppression | `is_foreign` interdit de supprimer, à raison tant qu'Open WebUI vit (un même fichier peut être dans plusieurs knowledge bases et ses conversations). Conséquence : un document supprimé dans Muffin laisse son objet. Lecture, aperçu, téléchargement et retraitement marchent tant que le compte S3 de Muffin lit ce préfixe | `core/storage.py` | C (décision) |
| 6 | **Compte S3 et clé Qdrant partagés** : aucune action tant que le même compte lit le préfixe d'Open WebUI | À garder comme contrainte documentée : si le préfixe change ou est purgé, les fichiers adoptés cassent | `docs/owui-test-instance.md` | S |
| 7 | **Nouveaux fichiers d'une collection adoptée** : ils vont dans `documents/…` de Muffin, et sont indexés dans `chunks_<id>` ; avant l'adoption, ils restent invisibles (§2) | Cohérent après la bascule ; avant, il faut la lecture seule (#9) | `DocumentUploadService` | B (via #4) |
| 8 | **Propriétaires sans compte Keycloak** : `owui:<id>` (propriétaire qui ne s'est jamais connecté par Keycloak) | Personne ne peut se connecter sous cet identifiant : seul un administrateur gère la collection. À réattribuer, au plus tard à l'adoption | `_UNKNOWN_OWNER` dans `owui_sync/app/tasks.py` | B |
| 9 | **Lecture seule du contenu d'une copie non adoptée** : 409 sur téléversement, ajout d'URL, suppression, retraitement, réglages, partage, renommage ; `source` et état d'adoption dans `CollectionOut` pour l'interface | Évite les effets du §2 pendant la cohabitation | services de contenu, `schemas/collection.py`, frontend | C |
| 10 | **Groupes copiés** : tant que la synchro tourne, rien. Le jour où elle est arrêtée pour de bon, il faut pouvoir les adopter (devenir des groupes de Muffin avec un propriétaire) | `_can_manage` et `_get_manageable` interdisent de modifier un groupe copié (`GroupReadOnlyError`) : sans synchro, plus personne ne peut changer leurs membres. Les partages qui y pointent restent valables | `GroupService`, `GroupSyncRepository` | B au moment d'arrêter la synchro |
| 11 | **Droits d'écriture copiés** : ils sont déjà des lignes `collection_shares` ; vérifier qu'aucune logique ne les relie encore à la synchro une fois la collection adoptée | | `CollectionSyncRepository.sync` | S |
| 12 | **Contenu natif** : après adoption, la collection garde ses pages uniques et les chunks d'Open WebUI (pas de citation ni d'aperçu par page, pas de mise en page, ni QA, tags, entités). Le retraitement de chaque document (`reprocess(bulk=True)`, qui relit le fichier là où il est) donne l'ingestion complète, au prix de l'OCR et des appels LLM, et remplace les chunks | À proposer à l'administrateur, collection par collection, après la bascule | `DocumentUploadService.reprocess` | C |
| 13 | **Coût de la réindexation** : réembedder tous les chunks avec le même modèle refait ce qu'Open WebUI a déjà calculé. Les deux index étant dans le même Qdrant, et les ids de points identiques, on peut recopier les vecteurs d'Open WebUI dans `chunks_<id>` et ne calculer que le BM25 quand le modèle est le même | Gain de temps et d'argent sur de gros volumes ; à chiffrer avant | `IndexRebuildService.submit` | C |
| 14 | **Changement de comportement de la recherche** : de dense seule à dense + BM25 fusionnés (RRF) ; les scores ne sont plus comparables à ceux d'avant la bascule | À annoncer, et à vérifier sur des questions réelles | `vector_store.search` | S |
| 15 | **Collections Qdrant d'Open WebUI** : elles restent. Ni suppression automatique ni nettoyage : elles servent de retour arrière tant que la synchro vit, et ne gênent pas (noms distincts de `chunks_<id>`) | Un nettoyage ne sera utile que le jour où Open WebUI est retiré | `vector_store` | C |
| 16 | **Retour arrière** : avant l'échange de l'alias, annuler lève la marque (déjà le cas pour une reconstruction). Après l'échange : la reconstruction existante garde l'ancien index jusqu'à validation, mais l'ancien ici serait celui de Muffin sans les chunks | À définir : rebasculer sur Open WebUI tant qu'il vit | adoption | S |
| 17 | **Tests** : réindexation d'une copie puis synchro (pas de doublon, pas d'écrasement) ; recherche avant, pendant et après la reconstruction ; annulation en cours ; document ajouté ou supprimé pendant la construction ; collection adoptée absente d'Open WebUI (pas de suppression) | Rien de cela n'est testé | `backend/tests`, `worker/owui_sync/tests` | B |

Ce qui **fonctionne déjà** avec le même Qdrant et le même S3, sans rien changer : lecture des copies par le Qdrant d'Open WebUI, résumés et description (#457), partages et groupes tels que copiés, routage, aperçu et téléchargement des fichiers sur place.

## 5. Ordre de travail proposé

1. #1, #9 : un seul prédicat « copiée » et lecture seule du contenu des copies, `source` dans l'API. Rend la cohabitation saine, sans effet visible pour les utilisateurs.
2. #2, #3, #4 et leurs tests (#17) : réindexer une copie, la synchro la laisse, la recherche bascule à l'échange. **C'est le cœur du scénario.**
3. #8 : propriétaires `owui:<id>`.
4. #13 : recopie des vecteurs, si les volumes le justifient.
5. #10 : adoption des groupes, au moment d'arrêter la synchro.
6. #12 : retraitement optionnel, collection par collection.

## 6. À vérifier avant de décider

- Volumes réels (fichiers, chunks) pour chiffrer #12 et #13.
- Le `hash` d'Open WebUI est-il le SHA-256 des octets du fichier, comme le `content_hash` de Muffin ? Si oui, un retraitement pourrait réutiliser des résultats (#300) ; non vérifié.
- Quand une collection est adoptée alors qu'Open WebUI continue d'y recevoir des fichiers : ils ne sont plus synchronisés. Faut-il le signaler à l'administrateur ?
- Pagination au-delà d'une page de l'API d'Open WebUI, gros volumes et déploiement Helm sur un cluster : jamais éprouvés en réel.
