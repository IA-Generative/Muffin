# Chercher dans Muffin depuis Open WebUI (#476)

Ce guide met en place, de bout en bout, l'**outil Muffin** d'Open WebUI : un utilisateur pose sa question dans le chat d'Open WebUI,
Muffin cherche dans ses collections **avec les droits de cet utilisateur**, et les documents trouvés apparaissent dans le panneau
« Sources » du message, avec leur nom et un lien qui les ouvre dans Muffin.

Le principe, le serveur MCP et ses réglages sont décrits dans [mcp.md](mcp.md) ; l'instance de test dans
[owui-test-instance.md](owui-test-instance.md). Ici : les étapes, dans l'ordre, et ce qu'il faut régler côté Keycloak.

## Ce qui est en jeu

```
 navigateur ──► Open WebUI ──(outil « Muffin », jeton Keycloak de l'utilisateur)──► Muffin  /api/mcp/
                    │                                                                   │
                    └── connexion par Keycloak (client open-webui)                      └── vérifie le jeton auprès de Keycloak (userinfo)
```

- L'utilisateur se connecte à Open WebUI **par Keycloak**, le même realm que Muffin. Open WebUI garde son jeton et le renouvelle.
- L'outil lit ce jeton (`__oauth_token__`) et appelle le serveur MCP de Muffin avec : Muffin sait donc **qui** cherche.
- Muffin ne vérifie pas pour quel client le jeton a été émis, seulement qu'il est valide dans son realm (appel `userinfo`, scope
  `openid`). Le jeton du client `open-webui` convient donc, à condition qu'il porte les mêmes informations que celui de
  `muffin-backend` : voir « Keycloak » plus bas.

## Prérequis

| Il faut | Pourquoi |
|---|---|
| Muffin à jour (serveur MCP `/api/mcp/`, #467) et au moins une collection | c'est ce que l'outil appelle |
| Un Keycloak commun à Muffin et Open WebUI | l'identité de l'utilisateur est la même des deux côtés |
| Open WebUI ≥ 0.12 | l'outil utilise les événements `citation` et `__oauth_token__` |
| Un compte administrateur d'Open WebUI et sa clé d'API | pour installer l'outil et l'assistant |
| Open WebUI qui **joint le backend de Muffin** sur le réseau | c'est Open WebUI (son serveur), pas le navigateur, qui appelle Muffin |
| Un modèle de chat dans Open WebUI | le modèle qui appelle l'outil et rédige la réponse |

## 1. Keycloak

### 1.1 Le client `open-webui`

Dans le realm de Muffin (`muffin` en test), un client OpenID Connect pour Open WebUI. Il existe déjà dans
`docker/keycloak/realm-muffin.json` ; en production, à créer (console d'administration → *Clients* → *Create client*) :

| Réglage | Valeur |
|---|---|
| Client ID | `open-webui` (le même que `OAUTH_CLIENT_ID` d'Open WebUI) |
| Client authentication | **On** (client confidentiel) ; le secret est dans l'onglet *Credentials*, il va dans `OAUTH_CLIENT_SECRET` |
| Standard flow | **On** |
| Direct access grants | Off |
| Valid redirect URIs | `https://<open-webui>/oauth/oidc/callback` |
| Web origins | `https://<open-webui>` |
| Client scopes par défaut | `openid`, `profile`, `email` |

Le scope **`openid`** est obligatoire : sans lui, Muffin ne peut pas lire l'identité du jeton (`userinfo`) et répond 401.

### 1.2 Les groupes et les rôles dans le jeton (à ne pas oublier)

Muffin décide de ce qu'un utilisateur voit et peut faire d'après son jeton : ses **groupes** (partage des collections avec un groupe)
et ses **rôles** du client `muffin-backend` (administrateur ou non). Ces informations viennent de deux *mappers* posés sur le client
`muffin-backend`. Un client `open-webui` créé « à neuf » **n'en a pas** : le jeton d'Open WebUI ne porte alors ni groupes ni rôles, et
l'utilisateur est traité comme un simple utilisateur sans groupe. Les collections partagées avec son groupe n'apparaissent pas dans
les sources, et un administrateur de Muffin cherche sans ses droits d'administrateur. Rien ne casse : les résultats sont seulement
incomplets, ce qui est difficile à remarquer.

Sur le client `open-webui` → onglet *Client scopes* → `open-webui-dedicated` → *Configure a new mapper* (ou *Add mapper → By
configuration*), deux mappers :

| Mapper | Type | Réglages |
|---|---|---|
| `groups` | *Group Membership* | Token Claim Name `groups` ; **Full group path : On** ; Add to access token **On** ; Add to ID token On ; Add to userinfo **On** |
| `client-roles-in-userinfo` | *User Client Role* | Client ID `muffin-backend` ; Multivalued On ; Token Claim Name `resource_access.muffin-backend.roles` ; Add to access token **On** ; Add to ID token On ; Add to userinfo **On** |

Ce sont les mêmes réglages que ceux de `muffin-backend` (`docker/keycloak/realm-muffin.json`).

Sur un Keycloak **déjà en route**, le fichier du realm n'est relu qu'à la première création du realm : ajouter les mappers par la
console ou par `kcadm.sh` :

```bash
K="docker exec -i muffin-keycloak-1 /opt/keycloak/bin/kcadm.sh"
$K config credentials --server http://localhost:8080 --realm master --user admin --password admin
CID=$($K get clients -r muffin -q clientId=open-webui --fields id --format csv --noquotes)
$K create clients/$CID/protocol-mappers/models -r muffin -f - <<'EOF'
{"name":"client-roles-in-userinfo","protocol":"openid-connect","protocolMapper":"oidc-usermodel-client-role-mapper",
 "config":{"usermodel.clientRoleMapping.clientId":"muffin-backend","claim.name":"resource_access.muffin-backend.roles",
 "jsonType.label":"String","multivalued":"true","id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}}
EOF
$K create clients/$CID/protocol-mappers/models -r muffin -f - <<'EOF'
{"name":"groups","protocol":"openid-connect","protocolMapper":"oidc-group-membership-mapper",
 "config":{"claim.name":"groups","full.path":"true","id.token.claim":"true","access.token.claim":"true","userinfo.token.claim":"true"}}
EOF
```

Les jetons déjà émis ne changent pas : **chaque utilisateur doit se déconnecter d'Open WebUI et s'y reconnecter** pour en avoir un
nouveau.

Les groupes de Keycloak ne sont pas les seuls pris en compte : Muffin y ajoute les groupes qu'il connaît lui-même pour cet
utilisateur (ceux que la synchronisation d'Open WebUI lui a recopiés, par exemple).

### 1.3 Durée des sessions

Open WebUI ne garde pas le mot de passe, seulement un jeton d'accès (5 minutes par défaut dans Keycloak) et un jeton de
renouvellement. Il renouvelle le premier avec le second avant chaque appel de l'outil. Le jeton de renouvellement vit **aussi
longtemps que la session Keycloak est active** : *Realm settings → Sessions → SSO Session Idle* (30 minutes par défaut) et *SSO
Session Max* (10 heures). Tant que l'utilisateur se sert de l'outil, le délai repart à chaque renouvellement ; après une pause plus
longue que *SSO Session Idle*, le renouvellement échoue, Open WebUI **supprime sa session OAuth** et l'outil répond que
l'utilisateur doit se reconnecter.

| Si les utilisateurs… | Alors |
|---|---|
| ouvrent Open WebUI dans la journée et le laissent ouvert | les valeurs par défaut suffisent |
| reviennent après plusieurs heures sur un chat resté ouvert | allonger *SSO Session Idle* (par exemple 8 h) et *SSO Session Max* |
| ne doivent jamais avoir à se reconnecter | ajouter le scope `offline_access` (`OAUTH_SCOPES: openid email profile offline_access` côté Open WebUI, et le laisser en *Optional client scope* du client `open-webui`) ; le jeton de renouvellement n'expire alors plus avec la session, mais seulement avec *Offline Session Idle* |

`offline_access` allonge aussi la durée pendant laquelle un jeton volé reste utile : ne l'activer que si le besoin est réel.

### 1.4 Ce qui n'est pas à régler côté Muffin

Rien dans le realm `muffin-backend` : pas de scope d'audience à ajouter, pas de redirection pour Open WebUI. Muffin reçoit le jeton
déjà émis et le fait contrôler par Keycloak. Son adresse interne vers Keycloak (`KEYCLOAK_URL`) doit être joignable du backend, comme
pour tout appel authentifié.

## 2. Open WebUI

Réglages d'environnement (voir `docker-compose.owui.yaml`, service `owui`, qui est un exemple complet) :

| Variable | Valeur | Rôle |
|---|---|---|
| `WEBUI_URL` | l'adresse publique d'Open WebUI | sert à construire le retour de la connexion |
| `ENABLE_OAUTH_SIGNUP` | `true` | un utilisateur de Keycloak est créé à sa première connexion |
| `OAUTH_PROVIDER_NAME` | `Keycloak` | libellé du bouton |
| `OAUTH_CLIENT_ID` / `OAUTH_CLIENT_SECRET` | `open-webui` / le secret du client | |
| `OPENID_PROVIDER_URL` | `https://<keycloak>/realms/<realm>/.well-known/openid-configuration` | joignable **du serveur** Open WebUI |
| `OPENID_REDIRECT_URI` | `https://<open-webui>/oauth/oidc/callback` | identique à celui du client |
| `OAUTH_SCOPES` | `openid email profile` | `openid` est indispensable |
| `ENABLE_API_KEYS` | `true` | pour créer la clé de l'installation (§3) |
| `OPENAI_API_BASE_URL` / `OPENAI_API_KEY` | le hub de modèles | le modèle qui rédige la réponse |
| `BYPASS_MODEL_ACCESS_CONTROL` | `true` **pour un essai seulement** | laisse tout utilisateur voir les modèles ; en production, partager le modèle « Assistant Muffin » avec les bons groupes à la place |

Seuls les utilisateurs **connectés par Keycloak** ont un jeton à transmettre. Un compte local d'Open WebUI (email + mot de passe) n'en
a pas : l'outil lui répond qu'il n'est pas connecté par Keycloak (voir le dépannage). Pour un déploiement où tous passent par
Keycloak, `ENABLE_LOGIN_FORM=false` retire le formulaire local ; garder au moins un compte administrateur local tant que la
connexion par Keycloak n'est pas éprouvée.

Open WebUI appelle **Muffin depuis son serveur** : l'adresse de la valve `MUFFIN_MCP_URL` (§3) doit être joignable depuis le
conteneur ou le pod d'Open WebUI. Dans le compose de test, `http://backend:8000/api/mcp/` ; en production, l'adresse du service du
backend dans le cluster (`http://<service-backend>.<namespace>.svc:8000/api/mcp/`) ou l'adresse publique en HTTPS. Le chemin `/api/mcp/`
finit par une barre oblique.

## 3. Installer l'outil et l'assistant

1. Dans Open WebUI, connecté en administrateur : *Paramètres → Compte → Clés d'API → Créer*. Copier la clé (`sk-…`).
2. Depuis un poste qui joint Open WebUI, à la racine du dépôt :

   ```bash
   OWUI_URL=https://<open-webui> OWUI_API_KEY=sk-... OWUI_BASE_MODEL=<identifiant d'un modèle d'Open WebUI> \
     python3 docker/owui/install_muffin_tool.py
   ```

   (en test : `OWUI_URL=http://localhost:3001`). `OWUI_BASE_MODEL` est l'identifiant du modèle sous l'assistant, tel que le liste
   *Workspace → Models* ou `GET /api/models`. Le script n'a besoin que de Python 3, sans bibliothèque.

   Il affiche `Muffin tool created: ['suggest_collections', 'search']`, puis `Assistant Muffin model ready, on <modèle>`. Il peut être
   relancé sans risque, et doit l'être après chaque modification de `docker/owui/muffin_search_tool.py`.

3. Ce qui a été créé, et qu'on peut ajuster dans *Workspace* :
   - l'outil **Muffin** (`suggest_collections`, `search`), partagé avec tous les utilisateurs ;
   - le modèle **Assistant Muffin** : le modèle de base, l'outil attaché, une consigne qui demande de s'en servir et de citer les
     sources par numéro, et les **outils intégrés d'Open WebUI coupés** (voir ci-dessous), partagé avec tous.
4. *Workspace → Tools → Muffin → ⚙ (Valves)* :

   | Valve | Rôle | Défaut |
   |---|---|---|
   | `MUFFIN_MCP_URL` | adresse du serveur MCP de Muffin, **à régler pour chaque déploiement** | `http://backend:8000/api/mcp/` |
   | `FALLBACK_TOKEN` | un jeton Keycloak collé à la main, utilisé seulement pour un utilisateur sans session Keycloak. **À laisser vide en production** : tous ceux qui n'ont pas de session chercheraient avec l'identité de ce jeton | vide |
   | `TIMEOUT_SECONDS` | délai d'une recherche (le découpage de la question par un modèle prend plusieurs secondes) | `120` |
   | `PASSAGE_CHARS` | longueur maximale d'un passage montré au modèle et dans le panneau | `1500` |

**Pourquoi couper les outils intégrés.** Avec eux, le modèle peut prendre les numéros de sources pour des identifiants de fichier et
ouvrir des fichiers qu'Open WebUI ne connaît pas (`File not found`, `Access denied to knowledge base`), puis conclure qu'il n'a
pas accès au contenu. Sans eux, il enchaîne `suggest_collections` puis `search` et cite. Le réglage est celui du modèle
(*Capabilities → Builtin Tools*, décoché) : il ne vaut que pour **Assistant Muffin**. Avec un autre modèle, l'outil Muffin peut
être activé à la main dans le chat, mais ce risque revient.

Côté Muffin, les bornes de la recherche (modèle de découpage, nombre de sous-questions, de collections, de sources) sont les
variables `MCP_*` de [environment-variables.md](environment-variables.md). Les liens des sources utilisent `FRONTEND_URL` du backend.

## 4. Essayer

1. Se déconnecter d'Open WebUI, puis **se connecter par le bouton « Keycloak »** (un compte du realm).
2. Ouvrir un nouveau chat, choisir le modèle **Assistant Muffin**.
3. Poser une question dont la réponse est dans un document auquel cet utilisateur a accès dans Muffin.

Résultat attendu : une réponse qui cite par `[1]`, `[2]`…, et sous le message un panneau « Sources » où chaque entrée porte le
**nom du document** (pas une adresse) ; cliquer ouvre le document dans Muffin. Dans les détails de l'appel d'outil, `search` a été
précédé de `suggest_collections`.

Vérifier les droits avec deux comptes (en test : `michou`, administrateur sans groupe, et `julie`, du groupe `/muffin-dev-team`, mot
de passe `muffin-dev`) : une collection partagée avec le seul groupe de `julie` apparaît dans ses sources et pas dans celles de
`michou` ; l'inverse pour une collection privée de `michou`. Si `julie` ne voit pas la collection de son groupe, ses jetons n'ont pas
les mappers du §1.2 (ou elle ne s'est pas reconnectée depuis).


## 5. Dépannage

| Ce qu'on voit | Cause probable | Quoi faire |
|---|---|---|
| « Muffin : l'utilisateur n'est pas connecté par Keycloak, la recherche est impossible. » | Compte local, ou session OAuth supprimée par Open WebUI (renouvellement impossible, §1.3) | Se déconnecter puis se reconnecter par le bouton Keycloak ; pour un essai, renseigner `FALLBACK_TOKEN` |
| « Muffin a refusé la connexion : l'utilisateur doit se reconnecter. » (401) | Jeton expiré ou sans scope `openid`, ou Keycloak que le backend ne joint pas | Se reconnecter ; vérifier `OAUTH_SCOPES` et `KEYCLOAK_URL` du backend |
| Erreur de connexion / délai dépassé à l'appel de l'outil | `MUFFIN_MCP_URL` injoignable depuis Open WebUI | Tester depuis le conteneur d'Open WebUI : `curl -i <MUFFIN_MCP_URL>` doit répondre (401 sans jeton, pas une erreur réseau) |
| Aucune source, ou « Aucune collection de Muffin ne correspond » | L'utilisateur n'a accès à aucune collection pertinente, ou ses jetons n'ont ni groupes ni rôles | Vérifier le partage dans Muffin ; vérifier les mappers du §1.2 et se reconnecter |
| Le modèle répond qu'il n'a pas accès aux fichiers (`File not found`, `Access denied to knowledge base`) | Les outils intégrés d'Open WebUI sont actifs sur le modèle | Utiliser **Assistant Muffin**, ou décocher *Builtin Tools* dans les capacités du modèle |
| Le modèle ne se sert pas de l'outil | Modèle de base sans appel de fonctions, ou outil non attaché | Choisir un modèle qui sait appeler des outils ; vérifier *Assistant Muffin → Tools → Muffin* |
| Les sources sont des adresses au lieu de noms | Ancienne version de l'outil | Relancer `install_muffin_tool.py` |
| L'utilisateur ne voit pas « Assistant Muffin » | Modèle non partagé avec lui et pas de `BYPASS_MODEL_ACCESS_CONTROL` | Partager le modèle (*Workspace → Models → Access*) |
| La connexion Keycloak échoue (`redirect_uri`) | URI de redirection du client différente de `OPENID_REDIRECT_URI` | Les aligner (§1.1, §2) |
| La page de connexion Keycloak s'ouvre sur une adresse que le navigateur ne joint pas | Keycloak annonce son adresse interne | Annoncer l'adresse publique pour le navigateur et l'adresse interne pour le serveur (`KC_HOSTNAME` et `KC_HOSTNAME_BACKCHANNEL_DYNAMIC` dans `docker-compose.owui.yaml`) |

## 6. Mettre à jour, retirer

- **Mettre à jour l'outil** : relancer le script d'installation (même commande). Les valves sont gardées à part par Open WebUI : elles ne sont
  pas écrasées.
- **Retirer** : *Workspace → Models → Assistant Muffin → supprimer*, puis *Workspace → Tools → Muffin → supprimer*. Le serveur MCP
  de Muffin n'est pas touché.
- **Autres clients** (un IDE, un agent) : ils parlent directement au serveur MCP, sans cet outil ; voir [mcp.md](mcp.md).

## 7. Limites connues

- L'identité vient de la session de connexion d'Open WebUI : pas de connexion Keycloak, pas de recherche avec les droits de la
  personne (hors `FALLBACK_TOKEN`).
- Le panneau « Sources » ne se remplit que par cet outil ; la connexion MCP seule d'Open WebUI donne un résultat sous forme de texte,
  sans panneau.
- Les numéros `[n]` sont ceux d'un message ; un nouveau message repart de 1.
- L'outil ne rédige pas : la réponse est celle du modèle d'Open WebUI, à partir des passages que Muffin renvoie.
