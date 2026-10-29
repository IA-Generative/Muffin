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

`ENV=dev` expose le schéma de l'API d'Open WebUI (http://localhost:3001/openapi.json et `/docs`), sur lequel le client de
synchronisation est écrit.

`ENABLE_PERSISTENT_CONFIG=false` : les variables d'environnement l'emportent toujours sur ce que l'interface d'administration a
enregistré. Sans cela, `ENABLE_API_KEYS` et les autres réglages restent figés à leur première valeur.

## Connexion par Keycloak

Open WebUI se connecte au Keycloak de Muffin (client `open-webui` du realm `muffin`, `docker/keycloak/realm-muffin.json`), comme en
production : un utilisateur connecté ainsi porte son sujet Keycloak dans `oauth.oidc.sub`, ce qui permet de rattacher les membres
d'un groupe à leur identité dans Muffin.

Keycloak annonce l'adresse `http://localhost:8080` pour la page de connexion (celle du navigateur) et `http://keycloak:8080` pour
ce que demande le serveur (jeton, clés) : même émetteur, joignable des deux côtés (`KC_HOSTNAME_BACKCHANNEL_DYNAMIC`).

Dans un navigateur, le bouton « Keycloak » de http://localhost:3001 ouvre la connexion. En script, `docker/owui/keycloak_login.py`
joue le même parcours et crée l'utilisateur dans Open WebUI à la première connexion :

```bash
python3 docker/owui/keycloak_login.py julie muffin-dev
python3 docker/owui/keycloak_login.py michou muffin-dev
```

Les comptes du realm sont `michou` (sans groupe) et `julie` (groupe `/muffin-dev-team`), mot de passe `muffin-dev`. Le `sub` lu par Open
WebUI est le même que celui que Muffin lit dans `userinfo`.

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
