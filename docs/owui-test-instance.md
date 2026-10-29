# Instance Open WebUI de test (#453)

Pour tester la synchronisation Open WebUI → Muffin contre une vraie instance, [docker-compose.owui.yaml](../docker-compose.owui.yaml)
ajoute au compose de Muffin Open WebUI **v0.12.5**, Tika et un bucket dédié. Comme en production, les deux applications
partagent le même S3 (RustFS), le même Qdrant et le même Keycloak.

```bash
docker compose -f docker-compose.yaml -f docker-compose.owui.yaml up -d rustfs qdrant keycloak owui
```

Open WebUI répond sur http://localhost:3001. La version se change avec `OWUI_VERSION`.

## Ce qui est partagé

| | Réglage côté Open WebUI |
|---|---|
| S3 | bucket `owui-files` sur RustFS (`STORAGE_PROVIDER=s3`), séparé de `muffin-documents` |
| Qdrant | mode classique : une collection `open-webui_<id de la knowledge base>` par knowledge base et une `open-webui_file-<id>` par fichier (`ENABLE_QDRANT_MULTITENANCY_MODE=false`) |
| Extraction | Tika (`CONTENT_EXTRACTION_ENGINE=tika`) : un seul document par fichier, sans numéro de page |
| Embeddings | le hub OpenAI-compatible de Muffin (`OPENAI_API_BASE_URL`, `OPENAI_API_KEY`), modèle `OWUI_EMBEDDING_MODEL` (par défaut `bge-multilingual-gemma2`) |

`ENABLE_PERSISTENT_CONFIG=false` : les variables d'environnement l'emportent toujours sur ce que l'interface d'administration a
enregistré. Sans cela, `ENABLE_API_KEYS` et les autres réglages restent figés à leur première valeur.

## Préparer des données

Le premier compte créé est administrateur. La synchronisation lit Open WebUI avec une clé d'API :

```bash
U=http://localhost:3001
curl -s -X POST $U/api/v1/auths/signup -H 'Content-Type: application/json' \
  -d '{"name":"Admin","email":"admin@example.test","password":"admin-dev-pass"}'
TOKEN=$(curl -s -X POST $U/api/v1/auths/signin -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.test","password":"admin-dev-pass"}' | jq -r .token)
KEY=$(curl -s -X POST $U/api/v1/auths/api_key -H "Authorization: Bearer $TOKEN" | jq -r .api_key)

KB=$(curl -s -X POST $U/api/v1/knowledge/create -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d '{"name":"kb-test","description":"test"}' | jq -r .id)
FILE=$(curl -s -X POST "$U/api/v1/files/?process=true" -H "Authorization: Bearer $KEY" -F file=@mon-fichier.pdf | jq -r .id)
curl -s -X POST $U/api/v1/knowledge/$KB/file/add -H "Authorization: Bearer $KEY" \
  -H 'Content-Type: application/json' -d "{\"file_id\":\"$FILE\"}"
```

## Ce que contient Open WebUI 0.12.5 (vérifié sur cette instance)

**Qdrant.** Un vecteur dense **sans nom**, en cosinus, de la dimension du modèle (3584 pour `bge-multilingual-gemma2`), sans vecteur
sparse. Le point a pour id l'id du chunk. Son payload :

```json
{
  "text": "...",
  "metadata": {
    "name": "test.txt", "source": "test.txt", "content_type": "text/plain", "size": 104,
    "file_id": "810b3a20-...", "file_hash": "4e04ce2a...", "hash": "4e04ce2a...",
    "created_by": "326b86da-...", "start_index": 0,
    "embedding_config": "{'engine': 'openai', 'model': 'bge-multilingual-gemma2'}"
  }
}
```

Pas de numéro de page avec Tika. `start_index` donne l'ordre des chunks et `embedding_config` le modèle d'embedding.

**S3.** Les fichiers sont à la racine du bucket : `<id du fichier>_<nom>`.

**Droits.** Open WebUI 0.12.5 n'utilise plus `access_control` mais `access_grants`, une liste d'objets
`{principal_type: "user" | "group", principal_id, permission: "read" | "write"}` portée par la knowledge base. L'identifiant `*` désigne
tout le monde. Les groupes ont un `parent_group_id` (hiérarchie).
