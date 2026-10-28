# worker/tabular - requêtes SQL sur les données tabulaires

Worker Celery qui exécute **une requête SQL en lecture seule** sur les copies Parquet typées des feuilles d'un fichier
tabulaire (#431). C'est ce que l'agent appellera pour interroger les données (#433) et ce qui alimentera les graphiques
(#434). Fait partie du ticket d'ensemble #430 ; rien n'y est encore branché : l'agent exécute toujours sa propre requête.

- Tâche `app.tasks.run_query(payload)` sur la queue `tabular_sql` (`SQL_QUEUE_NAME`) - pas `tabular_query`, qui est le
  nom de la tâche de l'agent. Le résultat reste une heure dans Redis.
- **Contrat** (`app/contracts.py`, pydantic, versionné) : la demande porte le SQL, les collections concernées et, pour
  chaque fichier, sa référence (`f1`, `f2`...) et ses feuilles (nom, clé du Parquet, colonnes avec leur type SQL). La
  réponse est un `QueryResult` (colonnes et types, lignes, `truncated`, durée) ou un `QueryFailure` (message, et la
  liste des tables interrogeables avec leurs colonnes). Une erreur de SQL n'est **jamais** une exception de la tâche :
  c'est un `QueryFailure`, que le modèle lit pour se corriger.
- **Nommage** : un fichier est un *schéma* (`f1`) et une feuille une *table* de ce schéma, nommée comme dans le fichier.
  Une jointure entre deux fichiers s'écrit donc comme entre deux feuilles :
  `SELECT … FROM f1."Ventes" v JOIN f2."Clients" c ON c."id" = v."client_id"`.
- **Le worker ne décide d'aucun droit d'accès** : il lit les clés qu'on lui donne, rien d'autre. Par défense en
  profondeur, il refuse (sans rien télécharger) une clé qui n'est pas celle d'une copie de feuille
  (`documents/{collection}/{document}/tables/{n}.parquet`) ou qui est d'une collection absente de la demande. C'est
  l'appelant qui construit la demande à partir des documents que l'utilisateur peut lire.
- **Le moteur** (`app/engine.py`, repris de spreadsheet-analyser, Apache-2.0) : le SQL est écrit par un modèle qui a lu
  des tableurs que n'importe qui a pu écrire, donc rien n'y est cru. Un dossier privé par requête ne contient que les
  Parquet autorisés ; DuckDB est verrouillé **avant** la requête (accès externe coupé sauf ce dossier, extensions non
  chargeables, configuration figée) ; une seule instruction, de type `SELECT` (le `PRAGMA`, que DuckDB réécrit en
  `SELECT`, est refusé sur ce qui est écrit) ; mémoire, threads, durée et taille du résultat bornés (`QUERY_*`,
  `docs/environment-variables.md`).
- **Droits S3** : le pod n'a besoin que de lire. Le chart lui donne le secret `muffin-s3-readonly` (une clé d'accès en
  lecture seule, distincte de celle des autres workers) ; il ne lit que les clés de copies de feuilles.

## Graphiques (#434)

Tâche `app.tasks.render_chart(payload)`, sur la même queue : la requête de l'agent est **rejouée** sur les mêmes feuilles
(jusqu'à `CHART_MAX_POINTS` lignes, davantage que ce que l'agent voit), et son résultat est dessiné avec `matplotlib`.

- La demande (`ChartRequest`) est celle d'une requête plus une `spec` : `type` (`bar`, `barh`, `line`, `area`, `pie`,
  `scatter`, `histogram`), `x`, `y` (jusqu'à 6 colonnes), `color`, `title`, `x_label`, `y_label`, `stacked`, `sort`.
  C'est une **description**, jamais du code. Le rendu réutilise le moteur de requête : il ne lit que les feuilles de la
  demande.
- La réponse est le PNG en base64 (`ChartResult`) : **le pod n'écrit rien dans le bucket** (sa clé est en lecture seule),
  c'est le backend qui le garde. Un graphique impossible (colonne inconnue, `y` non numérique, trop de catégories ou de
  séries, valeur négative dans un camembert) rend un `ChartFailure` qui dit quoi changer et donne les colonnes du résultat.
- Taille fixe (900 × 540 px à 125 dpi), palette lisible par les daltoniens, séparateur de milliers à la française, police
  DejaVu (accents, `€`). Le texte est dessiné tel quel : un `$` dans un titre n'ouvre pas de formule.
- `matplotlib` n'est dans l'image que de ce pod (pas dans l'image d'extraction) : elle fait environ 540 Mo.

## Mesures

Sur 5 millions de lignes (Parquet de 81 Mo, 5 colonnes), mémoire limitée à 512 Mo : une agrégation par catégorie ou
par jour prend 0,08 s ; un `GROUP BY` sur une colonne de 5 millions de valeurs distinctes 0,43 s, avec un pic de 380 Mo
pour le processus. Le pod du chart demande 1 Gi et plafonne à 2 Gi pour deux requêtes à la fois.

## Image

`python:3.12-slim`, `pip` retiré, non root, système de fichiers en lecture seule (le seul dossier inscriptible est
`/tmp`, où chaque requête a son dossier privé), aucun modèle, aucune extension DuckDB ; ne parle qu'à S3 et à Redis.

```bash
docker compose up worker-tabular
```

## Tests

```bash
uv run pytest
```

Ils reprennent les propriétés de sécurité du moteur d'origine (rien en dehors des tables listées n'est lisible, secrets
de l'environnement et variables Python hors de portée, réglages non modifiables, durée, mémoire) et celles de la tâche
(clé hors préfixe ou hors collection refusée avant tout téléchargement, bornes de fichiers et d'octets).
