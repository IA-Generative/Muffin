# Qdrant : sauvegarde et restauration

Qdrant est une instance unique (pas de réplication). Les vecteurs ne sont qu'ici ; PostgreSQL garde le texte, et une
reconstruction d'index (#12) peut tout recalculer, mais refait tous les embeddings (long et payant) : la sauvegarde sert à l'éviter.

## Sauvegarde

Un **snapshot de tout le stockage** (collections, alias, index) chaque nuit à 01:30, les 7 derniers conservés, écrits sur le volume
`qdrant-snapshots` du pod (`snapshotPersistence`). C'est le `CronJob` `qdrant-snapshot` de `helm/values/common-values.yaml` (la
planification, la rétention et l'image se règlent là). À la main :

```sh
curl -X POST -H "api-key: $QDRANT_API_KEY" "$QDRANT_URL/snapshots?wait=true"
curl -H "api-key: $QDRANT_API_KEY" "$QDRANT_URL/snapshots"
```

Le volume de snapshots est sur le même cluster que les données : pour survivre à la perte du cluster, en copier régulièrement
les fichiers hors du cluster.

## Restauration

Un snapshot complet se restaure au **démarrage** de Qdrant, sur un stockage vide. En Docker (vérifié, alias compris) :

```sh
docker run -d -p 6333:6333 -v /chemin/des/snapshots:/snap -v qdrant-data:/qdrant/storage \
  qdrant/qdrant:v1.20.0 ./qdrant --storage-snapshot /snap/full-snapshot-<date>.snapshot
```

Puis relancer Qdrant normalement (sans `--storage-snapshot`). Sur Kubernetes : arrêter le `StatefulSet`, vider le volume de données,
lancer une fois le pod avec cette même commande et le fichier de snapshot monté, puis rétablir le `StatefulSet` (non éprouvé sur le cluster).

Ce qui a été écrit depuis le snapshot manque : une reconstruction d'index (#12) de chaque collection le réconcilie avec PostgreSQL
(elle recalcule ce qui manque ou a changé).
