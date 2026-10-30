# Serveur MCP (#467)

Le backend sert MCP (Model Context Protocol) sur **`/api/mcp/`**, en HTTP « streamable » sans état, avec réponses JSON. Il offre la
recherche de Muffin à un client MCP (un assistant, un autre agent, Open WebUI) : **il renvoie des sources et n'écrit aucune
réponse**. Rien ne passe par l'agent, le worker ou Celery.

## Authentification

Un jeton d'accès **Keycloak** en `Authorization: Bearer …`, le même realm et les mêmes utilisateurs que l'API REST. Les collections
lisibles sont celles que l'utilisateur voit dans le chat : les siennes, celles partagées avec lui ou avec ses groupes (jeton et
groupes de Muffin), les publiques. Le cookie de session du navigateur n'est **pas** accepté : un navigateur l'envoie tout seul à
n'importe quelle page. Sans jeton valide : `401` avec `WWW-Authenticate: Bearer`.

## Outils

Les deux renvoient des **données structurées** (`structuredContent`, avec un schéma de sortie dans `tools/list`) et leur copie en
texte JSON.

### `suggest_collections(query, limit?)`

Les collections qui ont le plus de chances de contenir la réponse. Aucun modèle ne lit la question : elle est comparée aux
descriptions des collections lisibles (l'index `collections`). Une collection sans description indexée n'apparaît pas.

```json
{ "query": "…", "collections": [ { "id": "…", "name": "Congés", "path": ["RH", "Congés"], "description": "…", "score": 0.82, "url": "https://…/collections/…" } ] }
```

`path` ne contient que les ancêtres que l'appelant peut lire.

### `search(query, collection_ids?, model?, max_sub_queries?, max_collections?, limit?)`

1. Un modèle de chat découpe la question en sous-questions (un seul appel, pas de tâches ni de dépendances). Une question qui ne
   demande qu'une chose reste entière. Si l'appel échoue ou ne répond pas une liste, la question entière est l'unique sous-question.
2. Pour chaque sous-question : avec `collection_ids`, on ne cherche que dans ces collections ; sinon on prend ses `max_collections`
   meilleures collections (comme `suggest_collections`).
3. On interroge ces collections **sans filtre de type de point et sans cascade** : passages, questions déjà répondues et résumés
   ensemble, classés au cosinus (comparable d'une collection à l'autre). `limit` résultats par sous-question.

```json
{ "query": "…", "model": "…",
  "sub_queries": [ { "text": "…",
    "collections": [ { "id": "…", "name": "…", "path": ["…"], "description": "…", "score": 0.8 } ],
    "sources": [ { "kind": "chunk|qa|summary", "text": "…", "score": 0.71, "document_id": "…", "document_name": "…",
                   "page": 3, "collection_id": "…", "collection_name": "…", "url": "https://…/collections/…/documents/…" } ] } ] }
```

- `kind` : `chunk` (passage d'un document), `qa` (question et réponse), `summary` (résumé du document). `page` est la première page
  du passage quand elle est connue, sinon `null`.
- `url` : où ouvrir le document (ou la collection, pour une question sans document, et pour les collections proposées) dans
  l'interface de Muffin, construit avec `FRONTEND_URL`. Le même lien quel que soit le client (Muffin, Open WebUI…).
- Avec `collection_ids`, `collections[].score` vaut `0` : aucune sélection n'a eu lieu.
- Une collection de `collection_ids` que l'appelant ne peut pas lire (ou qui n'existe pas) fait **refuser** l'appel (erreur d'outil),
  sans rien chercher.
- Les collections copiées d'Open WebUI sont lues dans le Qdrant d'Open WebUI, qui ne contient que des passages, en dense seul
  (voir `search.md`) : leurs sources sont des `chunk`.
- Un appel coûte un appel au modèle de chat (le découpage, enregistré dans la consommation, `step = mcp_split`) et des embeddings
  (un par modèle d'embedding des collections interrogées, par sous-question).

## Depuis Open WebUI (essayé sur la v0.12.5)

Déclaré comme serveur d'outils de type `mcp` (administration → Outils, ou `POST /api/v1/configs/tool_servers`), avec l'adresse
`http://backend:8000/api/mcp/` et une authentification « bearer ». Open WebUI liste alors les deux outils avec leurs paramètres
(`muffin_suggest_collections`, `muffin_search`).

Dans son chat, avec les outils activés pour la conversation, le modèle a **enchaîné de lui-même** `suggest_collections` puis `search`
avec les collections proposées, et a répondu en citant le nom du document et son lien Muffin pour chaque fait.

Ce qui reste vrai de ce côté :

- Le résultat arrive au modèle comme du **texte** (le JSON), pas comme des sources d'Open WebUI : son panneau « Sources » reste
  vide, et les appels d'outils s'affichent dans les blocs repliables du message. C'est au modèle de citer les sources, d'où le lien
  `url` de chaque source.
- Le jeton est un jeton Keycloak, **valable quelques minutes** : un jeton saisi une fois dans Open WebUI cesse de marcher. Un usage
  durable demande qu'Open WebUI obtienne lui-même son jeton (OAuth) ou un compte de service ; notre serveur n'annonce pas encore de
  métadonnées OAuth pour qu'il le découvre.
- L'appel par l'API `POST /api/chat/completions` seule n'exécute pas les outils : il rend l'appel au client. Ils s'exécutent dans le
  fil d'un chat, comme le fait l'interface.

## Réglages

Voir `MCP_*` dans `environment-variables.md` : modèle de découpage par défaut, valeurs par défaut de chaque borne et plafonds
qu'aucun appel ne dépasse.

## Hors périmètre

Filtre par fichier (`document_ids`, qui demande un filtre par identifiants de points ou le `document_id` du payload, #468),
rédaction d'une réponse (l'agent, #21), retour d'avis, analyse d'URL.
