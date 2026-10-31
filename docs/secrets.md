# Secrets que Muffin doit relire (#521)

Certaines fonctions obligent Muffin à **relire** un secret pour s'en servir : la clé d'un service qu'il appelle pour un utilisateur
(transcription, images), le jeton d'un serveur MCP, un connecteur de source. Ceux-là ne peuvent pas être hachés comme une clé
d'API (voir `api-keys.md`, où Muffin ne fait que *vérifier*) : ils sont **chiffrés** avant d'aller en base, et ne sont ouverts qu'à
l'endroit où ils servent.

Ce module (`app/core/secret_store`, `app/services/secret_store_service.py`) n'a pas encore de fonction qui l'utilise : il est
posé pour #517, #518 et #343.

## Ce qu'on garde, et où

| | |
|---|---|
| Base de données | `stored_secrets` : le **texte chiffré** (`vault:v3:…` ou `local:k2:…`), la version de la clé, les 4 derniers caractères d'un secret d'au moins 16 caractères (pour distinguer deux secrets à l'écran, jamais pour l'utiliser), qui l'a créé, quand il a été utilisé. **Jamais le secret.** |
| Clé de chiffrement | Dans **Vault** (Transit), qui ne la donne jamais à l'application ; ou, sans Vault, dans le jeu de clés de la configuration. Jamais à côté des secrets qu'elle chiffre. |
| API | **Aucune route ne renvoie un secret.** Un champ secret est en écriture seule ; l'interface montre `••••` et les derniers caractères. |
| Journaux | L'identifiant, l'usage et le propriétaire d'un secret, jamais sa valeur ni son texte chiffré. |

## Liaison à la ligne

Chaque secret est chiffré avec un **contexte** : `identifiant de la ligne | propriétaire | usage`. Le texte chiffré ne s'ouvre que pour
ce contexte. Quelqu'un qui peut écrire dans la base et copie le secret d'Alice sur la ligne de Mallory n'obtient rien : il ne
s'ouvre pas là. Avec Vault, c'est le rôle de la clé *dérivée* (`derived=true`) ; en local, ce sont les données associées d'AES-GCM.

## Deux fournisseurs

### Vault Transit (production)

L'application envoie le secret à chiffrer et reçoit un texte que seul Vault sait ouvrir. Le jeton de l'application ne permet **que**
`encrypt`, `decrypt` et `rewrap` sur sa clé.

Mise en place (par l'exploitation de Vault) :

```bash
vault secrets enable transit
vault write -f transit/keys/muffin-secrets derived=true

vault policy write muffin-app - <<'POLICY'
path "transit/encrypt/muffin-secrets" { capabilities = ["update"] }
path "transit/decrypt/muffin-secrets" { capabilities = ["update"] }
path "transit/rewrap/muffin-secrets"  { capabilities = ["update"] }
POLICY

vault auth enable kubernetes
vault write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc
vault write auth/kubernetes/role/muffin \
    bound_service_account_names=muffin-backend bound_service_account_namespaces=muffin \
    policies=muffin-app ttl=15m
```

> **N'accordez jamais `create` sur ces chemins.** Avec `create`, Transit **invente** une clé (non dérivée) quand on lui en demande une
> qui n'existe pas, au lieu de répondre par une erreur : un nom mal écrit chiffrerait alors des secrets sous une clé que personne
> n'a prévue. Avec `update` seulement, une clé absente donne `403`. Les tests (`tests/core/test_secret_store_vault.py`)
> vérifient que cette politique suffit, que l'application ne peut ni lire, ni faire tourner, ni exporter, ni supprimer sa clé, et
> qu'une clé absente n'est pas créée.

Côté Muffin :

```
SECRETS_PROVIDER=vault
SECRETS_REQUIRE_VAULT=true        # refuser de démarrer sans Vault
VAULT_ADDR=https://vault.example:8200
VAULT_TRANSIT_KEY=muffin-secrets
VAULT_AUTH_METHOD=kubernetes       # le compte de service du pod ; VAULT_K8S_ROLE=muffin
```

Le jeton du compte de service s'échange contre un jeton Vault **court** (renouvelé aux 80 % de son bail). Si Vault répond `403` à un
jeton qui n'est plus connu, l'application se reconnecte **une fois** puis abandonne. Une clé Transit par environnement
(`muffin-<env>-secrets`).

### Jeu de clés local (développement, tests, sans Vault)

AES-256-GCM (bibliothèque `cryptography`), nonce unique de 12 octets à chaque chiffrement, contexte authentifié.

```bash
python -c "import secrets,base64;print(base64.b64encode(secrets.token_bytes(32)).decode())"
SECRETS_LOCAL_KEYS="k2=<clé>,k1=<ancienne clé>"     # la première chiffre, les autres ne font que déchiffrer
```

L'application **journalise un avertissement au démarrage** avec ce fournisseur. `SECRETS_REQUIRE_VAULT=true` l'interdit. La clé est un
secret Kubernetes : elle protège d'une fuite de la **base seule**, pas d'un accès au pod.

## Échec fermé

- Vault injoignable, scellé, ou qui refuse l'application : la fonction qui avait besoin du secret répond **503**. Rien ne retombe sur un
  fournisseur moins sûr.
- Aucune clé locale et pas de Vault : aucun secret ne peut être stocké (la fonction qui en a besoin est indisponible).
- `SECRETS_REQUIRE_VAULT=true` sans Vault, ou `vault` sans `VAULT_ADDR`, ou un fournisseur inconnu, ou une clé locale mal formée : **l'application ne
  démarre pas**.
- Un texte chiffré qui ne s'ouvre pas (altéré, copié d'une autre ligne, clé retirée du jeu) lève `SecretDecryptionError`, sans valeur.

## Rotation de la clé

1. **Vault** : `vault write -f transit/keys/muffin-secrets/rotate`. Les anciens textes restent lisibles ; les nouveaux portent `v2`.
   (Local : mettre la nouvelle clé **en premier** dans `SECRETS_LOCAL_KEYS`, garder l'ancienne.)
2. **Voir la progression** : `GET /api/admin/secrets/status` (administrateur) → fournisseur, joignable ou non, version courante, nombre de secrets par
   version, nombre à réécrire.
3. **Réécrire** : `POST /api/admin/secrets/rewrap?limit=200`, à répéter jusqu'à `remaining: 0`. Avec Vault, c'est `rewrap` : Vault réécrit le texte
   sous la dernière version **sans que le secret passe par l'application**. (Une tâche planifiée viendra ; en attendant, un `cron`
   suffit.)
4. **Retirer l'ancienne version** : `vault write transit/keys/muffin-secrets/config min_decryption_version=2` (local : retirer l'ancienne clé du jeu).
   À ne faire que lorsque `stale` est à 0 : un texte non réécrit ne s'ouvrirait plus.

## Sauvegardes

**Perdre la clé Transit, c'est perdre tous les secrets chiffrés** (et, en local, perdre le jeu de clés). Sauvegarder Vault
(instantanés Raft), **tester une restauration réelle**, et garder le jeu de clés local hors de la base qu'il protège.

## Pour un développeur

```python
store = SecretStore(db)                       # le fournisseur vient de la configuration
secret = await store.put(owner=user.user_id, purpose="transcription.api_key", plaintext=key, created_by=user.user_id)
await db.commit()                             # l'appelant valide, comme pour un dépôt
...
key = await store.reveal(secret.id, owner=user.user_id, purpose="transcription.api_key")   # là où on s'en sert
```

- `purpose` est fixé **par le code**, jamais par un utilisateur (`[a-z0-9._:-]`, 100 caractères au plus).
- Un propriétaire ou un usage qui n'est pas celui de la ligne est traité comme une ligne qui n'existe pas.
- `replace`, `delete`, `rewrap_batch`, `versions` complètent l'interface. Une erreur de fournisseur est une `SecretStoreError`
  (jamais une valeur secrète) : la traduire en 503.

## Essais

Les tests tournent contre un Vault de développement (`docker compose -f docker-compose-test.yaml up -d vault-test`, `VAULT_TEST_ADDR`
dans `tests/.env.testing`; en CI, un service `hashicorp/vault`) : chiffrement, contexte, rotation, rewrap, politique minimale. Les
cas qu'un vrai Vault ne produit pas sur demande (injoignable, scellé, jeton révoqué, connexion Kubernetes) le sont contre un Vault
simulé.

## Pas encore fait (#521)

- Table d'audit des accès aux secrets (qui, quand, quel usage) et masquage des valeurs dans les journaux et les traces d'exécution par un filtre.
- Tâche planifiée de `rewrap`.
- Lecture du poivre des clés d'API dans Vault (aujourd'hui un secret Kubernetes).
- Chart Helm : valeurs dédiées (rôle, adresse, certificat), option des secrets montés en fichiers.
