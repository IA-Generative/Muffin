# Recherche : Qdrant, dense + BM25, fusion RRF (#355)

Tout l'index de recherche est dans **Qdrant**, derrière `backend/app/services/vector_store.py`. Les workers n'y accèdent jamais :
ils passent par les endpoints internes du backend. Réglages : [environment-variables.md](environment-variables.md#recherche-hybride-qdrant).
Sauvegarde et restauration : [qdrant-backup.md](qdrant-backup.md).

## Modèle de données

- Une collection Qdrant par collection Muffin (les modèles d'embedding et les dimensions diffèrent d'une collection à l'autre ;
  la supprimer reste triviale), plus une collection `collections` pour les descriptions (routage, suggestion de rangement).
- Chaque point a deux **vecteurs nommés** : `dense` (cosinus, dimension du modèle de la collection) et `sparse` (BM25, avec le
  **modificateur IDF** de Qdrant : le serveur calcule l'IDF depuis les statistiques de la collection, le client n'envoie que la
  fréquence saturée de chaque terme).
- Payload : `kind` (`chunk`, `qa`, `summary`), `collection_id`, `text`, `model` (le modèle qui a fait le vecteur, ce que la
  reconstruction compare). Index de payload sur `kind` et `collection_id`. L'identifiant du point est celui de la ligne Postgres.
- Qdrant **normalise** les vecteurs d'une collection cosinus à l'écriture : un vecteur relu (réutilisation, #300) a la même
  direction, pas la même norme - sans effet sur le cosinus.

## Vecteur épars lexical (BM25)

Calculé côté application (`backend/app/core/bm25.py`), le même calcul à l'indexation et à la requête : minuscules, accents retirés,
mots vides retirés, racinisation Snowball (`py-rust-stemmers`, français par défaut, `SEARCH_LANGUAGE`). Un terme devient un entier
32 bits (CRC32). Valeur d'un terme dans un texte : `tf × (k1 + 1) / (tf + k1 × (1 − b + b × longueur / longueur_moyenne))` ; dans une
requête : 1 par terme distinct. Le texte indexé est celui de `text`, pour les trois sortes de points ; pour une collection, la
description suivie des étiquettes.

**Perte par rapport à Meilisearch** : Meilisearch tolérait les fautes de frappe et cherchait les préfixes, BM25 non - ni
`stationnemet` pour `stationnement`, ni `statio`. (La racinisation rattrape les variations de forme : `stationement` →
`stationnement`.) Sur une requête mal écrite, seule la branche dense travaille. Cette perte n'est pas encore chiffrée sur les
questions de test de l'évaluation (#260) : à mesurer avant de mettre en production.

## Requête hybride

Une requête de l'API Query de Qdrant : deux `prefetch` (dense et épars, chacun avec son filtre `kind` et son plafond de
candidats `SEARCH_PREFETCH_LIMIT`), puis une fusion **RRF** (`SEARCH_RRF_K`, poids par branche). Une requête qui ne contient que des
mots vides n'a pas de branche lexicale : la branche dense répond seule. `search`, `search_qa`, `search_summaries` et
`search_collections` gardent leur signature ; `search_collections` ne sort jamais de la liste de candidats qu'on lui donne (déjà
filtrée par droits).

### Le score

Un score RRF ne dépend que des rangs (de l'ordre de `1/(k+rang)` sommé) : il n'est pas une similarité, et ne se compare pas d'une
requête à l'autre. **L'ordre des résultats vient de la fusion ; `relevance_score` (lu par l'agent, affiché, utilisé pour fusionner
les résultats de plusieurs collections) est le cosinus entre la requête et le vecteur dense du résultat**, calculé côté backend
sur le vecteur renvoyé avec le point. Il vaut donc la même chose quelle que soit la branche qui a trouvé le point : un point
trouvé seulement par la branche lexicale (un code, un nom propre) a le cosinus, souvent bas, de son embedding.

Conséquence : la décision « cette question a déjà été répondue » (`_QA_MATCH_THRESHOLD = 0.85`, `worker/agent_execution/.../research_task.py`)
porte sur ce cosinus, pas sur un score de fusion, et un point lexical-seul ne la franchit pas. La fusion pouvant mettre
en tête un point au cosinus plus faible qu'un suivant, l'agent demande les 3 premiers candidats (déjà triés par cosinus par le
backend) et regarde le meilleur. **Le seuil 0,85 n'est pas recalibré** : il le sera avec les paires de test de l'évaluation, ce
qui demande des données réelles.

### Observer chaque branche

`SEARCH_LOG_BRANCHES=true` journalise (debug), pour chaque recherche, le rang que chaque branche donnerait seule à chaque résultat ;
`vector_store.explain_search` renvoie la même chose (utilisé par les tests).

## Écriture, lecture, suppression

- Écritures par lots, avec `wait=true` : ce qu'on relit juste après est déjà là.
- `read_vectors` : un seul appel pour N points (`retrieve`), par paquets de 1000.
- `list_points` : `scroll` paginé.
- Suppressions par identifiants, dans la collection active et celle d'une reconstruction en cours.

## Reconstruction blue/green (#12)

La collection active est désignée par un **alias** `chunks_<id>` : lectures et écritures passent par lui. Derrière, deux collections
physiques, `chunks_<id>_a` et `chunks_<id>_b`, utilisées à tour de rôle : la reconstruction construit celle sur laquelle l'alias ne
pointe pas (« next »), puis **déplace l'alias** d'une collection à l'autre dans une seule requête (suppression et création de
l'alias ensemble : atomique côté Qdrant). Toute recherche avant la bascule lit l'ancien index, toute recherche après le nouveau,
jamais rien entre les deux - même avec une autre dimension. L'ancien reste, comme « next », jusqu'à validation (supprimé) ou retour
arrière (la même bascule dans l'autre sens). Une collection sans index avant la reconstruction reçoit son alias directement sur le
nouvel index.

## Données existantes

Les données de Meilisearch ne sont pas migrées : un index Qdrant se remplit à l'indexation d'un document, ou par une reconstruction
(#12), qui le recalcule depuis PostgreSQL (les embeddings sont refaits). Une collection déjà indexée doit donc être reconstruite
une fois après le déploiement.
