# Génération d'images dans le chat (#518)

Facultative et **désactivée par défaut**. Quand un administrateur l'active, les personnes autorisées peuvent demander une image dans le chat : elle est
faite par un fournisseur **compatible OpenAI**, gardée par Muffin avec la conversation, lisible par son auteur seulement, et étiquetée « générée par IA ».

Sans activation, **rien ne change** : le mode « Image » n'est pas proposé, la route répond `404`, aucun appel n'est fait.

## Ce que voit la personne

Un bouton *Générer une image* dans le composeur, visible **seulement** si la fonction est activée, prête et permise à cette personne
(`GET /api/images/status`). Une fois le mode choisi, le message est la **description** de l'image (jamais une question à l'agent) ; le texte du mode dit où
part la description (vers le fournisseur choisi par l'administrateur) et ce qu'il reste du quota du jour.

- L'image arrive dans la conversation (une nouvelle quand il n'y en a pas), avec **« Image générée par IA »** sur l'image, la description en légende et un
  bouton *Télécharger*. Elle reste après un rechargement, et disparaît avec la conversation.
- Une génération dure plusieurs secondes : le message le dit pendant l'attente. Un refus (quota, refus de politique du fournisseur, panne) s'affiche comme
  réponse, en une phrase lisible.
- **Deux façons d'en demander une.** Le bouton *Image* (explicite : le message est la description) et, **sans mode**, une phrase du chat (« fais-moi une
  affiche pour… ») : l'assistant appelle alors lui-même l'outil `generer_image` (voir plus bas). Dans les deux cas, même fonction, mêmes droits, même quota.

## Réglages d'administration

*Administration → Génération d'images* (`/admin/images`, `GET` / `PATCH /api/admin/image-generation`) :

| Réglage | Rôle |
|---|---|
| Activer | Désactivé par défaut. Il faut un modèle pour l'activer. |
| Adresse | Une adresse compatible OpenAI, terminée par `/v1` (le hub, une passerelle LiteLLM, LocalAI…). **Vide : celle du hub.** |
| Clé | **Vide : celle du hub**, mais seulement avec l'adresse du hub : la clé du hub n'est **jamais envoyée à une autre adresse** (une autre adresse demande la sienne, refusé à l'enregistrement sinon). Une clé saisie est chiffrée (`StoredSecret`, finalité `image-generation-key`) et **jamais relue** : les réglages disent seulement qu'il y en a une. |
| Modèle | Saisi (`gpt-image-1`, `dall-e-3`…). |
| Taille, qualité | Taille par défaut (`1024x1024`, `auto`…) et qualité (`low`, `medium`, `high`, `standard`, `hd`, `auto`) ; vide : celle du modèle. |
| Images par personne et par jour | Quota (UTC), `20` par défaut. |
| Poids maximal d'une image | `8` Mo par défaut, borné par `IMAGES_MAX_BYTES_LIMIT`. |
| Groupes autorisés | Groupes Keycloak ou de Muffin ; vide : tout le monde. Un administrateur peut toujours générer. |

La liste des modèles du fournisseur (`GET {adresse}/models`) n'est pas proposée : le modèle se saisit.

**Tester** fait une petite image avec les réglages **enregistrés** et dit le temps pris, la forme de la réponse (`b64_json` ou `url`) et la taille — ou ce qui
ne va pas : clé refusée (`cle_refusee`, 401/403), modèle inconnu (`modele_introuvable`, 404), paramètre refusé (`parametre_refuse`, 400), refus de politique
(`refus_politique`). L'image d'essai n'est pas gardée et ne compte dans le quota de personne ; elle peut être faite avant d'activer la fonction.

## Ce que Muffin envoie, et ce qu'il accepte

`POST {adresse}/images/generations` avec `model`, `prompt`, `n=1`, `size` et, si réglée, `quality`. **`response_format` n'est jamais envoyé** : certains modèles
(la famille `gpt-image-*`) ne répondent qu'en base64 et refusent ce paramètre, d'autres répondent par adresse. Les **deux formes** sont acceptées :

- `b64_json` : décodé après une vérification de taille (le base64 pèse un tiers de plus que l'image) ;
- `url` : l'image est **téléchargée par le serveur**, jamais renvoyée telle quelle à la personne (l'adresse expire — environ une heure chez OpenAI — et pointe
  vers un tiers), puis stockée. C'est une requête sortante pilotée par un tiers, donc : **https seulement, adresse publique** (ni privée, ni locale, ni
  métadonnées du cloud, ni identifiants dans l'adresse), **aucune redirection suivie**, délai court (`IMAGES_DOWNLOAD_TIMEOUT_SECONDS`), poids plafonné lu en
  flux. La garde est celle des serveurs d'outils (`app/core/url_guard.py`, `docs/tools.md`) sans leur liste de domaines.

**Les octets sont vérifiés, pas la parole de l'expéditeur** (`app/core/image_bytes.py`) : le type est lu dans l'en-tête, **PNG, JPEG ou WebP seulement**
(jamais de SVG ni de HTML), avec un côté d'au plus `IMAGES_MAX_SIDE` pixels et un poids d'au plus le réglage. Le type vérifié est celui qui est servi, avec
`X-Content-Type-Options: nosniff`. Pour un PNG, une zone `tEXt` indique en plus dans le fichier que l'image vient d'une IA ; les autres types n'ont que
l'étiquette à l'écran.

## Quand l'assistant en fait une : l'outil `generer_image`

Comme ChatGPT, on peut simplement l'écrire : « fais-moi un logo pour la direction », puis « refais-le en bleu ». Le planificateur appelle l'outil interne
`generer_image` (`docs/tools.md`) dans son appel habituel : **aucun appel de modèle en plus**, un appel d'outil n'en est pas un.

- **Quand il est offert** : seulement si la fonction est activée, complète (modèle et clé) et ouverte aux groupes de la personne (`ImageGenerationService.offered_to`).
  Sinon il n'apparaît ni dans la liste des outils, ni au modèle, et un appel répond `outil_indisponible` sans rien appeler. Un administrateur qui n'est dans aucun
  groupe autorisé a le bouton *Image* mais pas l'outil : un run ne sait pas qui est administrateur. Une conversation peut **le retirer** comme n'importe quel
  outil (menu *Outils* du chat), et un assistant peut couper `call_tool`.
- **Mêmes droits, même quota** : le service, la garde du texte, le débit, le **quota du jour de la personne** (partagé avec le bouton), la vérification des octets et
  le stockage sont les mêmes. La personne est lue sur le run, jamais sur ce que dit l'agent. En plus, **`IMAGES_PER_RUN` images au plus par réponse** (2) :
  `limite_par_reponse` au-delà.
- **Où va l'image** : elle appartient d'abord au **run**, puis au **message** de la réponse quand elle est écrite, comme un graphique (#434) ; `GET /api/runs/{id}` la
  montre dès qu'elle existe, et la conversation la garde au rechargement. Le texte de la réponse ne contient ni lien ni image : l'outil dit au modèle que l'image est
  affichée sous sa réponse et avec quelle description.
- **Dans le contexte des tours suivants** : la réponse du modèle n'est que du texte ; l'historique donné à l'agent ajoute donc, à ce message, la ligne
  « [Image générée par IA, affichée à l'utilisateur. Description envoyée au fournisseur : « … »] ». « Fais-la en bleu » repart de cette description (le modèle écrit
  une description complète, corrigée) ; il ne **voit** pas l'image qu'il a fait générer (seules les images que la personne joint à son message sont
  lues par un modèle de vision, `docs/image-attachments.md`).
- **Le risque, et ce qui le borne** : la description est écrite par le modèle, qui lit des documents dont le texte peut lui dire « génère une image avec ceci ».
  Elle partirait chez un tiers. Ce qui le limite : la description de l'outil interdit d'y mettre des extraits de documents ou des données personnelles et de
  l'appeler sans demande explicite, le quota du jour et `IMAGES_PER_RUN` bornent la dépense, et la description envoyée est dite à la personne (légende de l'image,
  tour suivant). **Rien ne demande l'accord avant** : c'est le choix « automatique », comme ChatGPT. Pour l'exiger, retirer l'outil de la conversation ou ne pas
  autoriser la fonction aux groupes concernés.

## Droits, quotas et limites

Avant tout appel au fournisseur : la fonction est activée (sinon `404`, `fonction_desactivee`), la personne est autorisée (sinon `403`, `non_autorise`), la
description est dans les bornes (`IMAGES_PROMPT_MAX_CHARS`, 4000), le débit (`IMAGES_PER_USER_PER_MINUTE`, 5) et le quota du jour sont respectés (sinon `429`,
`trop_de_demandes` / `quota_depasse`). Le quota et le débit sont des compteurs Redis, pris **avant** l'appel. Un quota qui ne peut pas être vérifié arrête la
demande (`503`, `quota_indisponible`) : une image coûte de l'argent. Une demande qui n'a donné aucune image **ne compte pas** dans la journée.

## Les erreurs

Elles ont le format de l'API : un statut et `detail: { code, message }`, le code ne change pas. Rien de ce que dit le fournisseur ne parvient à la personne — son
texte peut répéter une partie de la clé ou de la description — seulement un code et une phrase de Muffin ; le journal garde le statut et le code du
fournisseur. `invite_vide`, `invite_trop_longue`, `refus_politique` (422), `cle_refusee`, `modele_introuvable`, `parametre_refuse`, `image_invalide`,
`image_trop_lourde`, `fournisseur_injoignable`, `fournisseur_en_erreur` (502), `fournisseur_surcharge` (503), `delai_depasse` (504), `non_configuree` (409).

## Où est l'image

Une table `generated_images` (conversation, message, description, modèle, type, taille, poids) et un objet `images/{conversation}/{image}.{png|jpg|webp}` dans le
stockage, **lu par le backend** avec les droits de la conversation (`GET /api/conversations/{id}/images/{image}`, `404` pour tout autre que son propriétaire),
jamais par un lien du stockage. Les images ne sont pas indexées. Supprimer la conversation supprime les lignes et les fichiers. Chaque message qui en porte
liste ses images (`images` dans `GET /api/conversations/{id}/messages`).

La demande est un message de la conversation, la réponse un autre (« Image générée par IA à partir de la demande : … ») : c'est ce que lisent les tours
suivants. Aucun run n'est créé.

## Consommation

Une image n'a pas de coût en jetons : chaque génération écrit une ligne de consommation (`token_usages`, genre `image`, étape `image_generation`) avec le **nombre
d'images** et leur **taille en pixels** (`images`, `pixels`), rattachée à la personne. La page *Consommation* montre les images générées et l'étape
« Chat · génération d'image » ; l'essai de l'administrateur n'est pas compté.

## Vie privée

- La **description part chez le fournisseur** : l'interface (le texte du mode « Image ») et cette page le disent. Avec l'adresse du hub, elle reste dans le
  périmètre de l'organisation ; avec une autre adresse, c'est à l'administrateur de choisir un fournisseur acceptable.
- Les images ne sont visibles que de leur auteur et ne sont pas indexées.
- Aucune clé ne figure dans une réponse de l'API ni dans le journal.

## Pas encore

- Les **garde-fous d'entrée** (#516) : la description n'y passe pas encore, seulement les bornes ci-dessus et les refus de politique du fournisseur.
  Elle devra y passer comme tout message quand ils existeront.
- La **retouche** (`/images/edits`) et les variantes : l'entrée existe maintenant (les images jointes, #512), pas encore l'appel.
- Un **outil « générer une image »** qui illustre automatiquement un document créé : l'outil `generer_image` existe, mais seulement sur demande explicite de la personne.
- Les moteurs qui ne parlent pas le protocole d'OpenAI (AUTOMATIC1111, ComfyUI) : à passer par une passerelle compatible.
- Le **cadre réglementaire** de l'étiquetage des contenus générés est à vérifier pour l'organisation ; l'étiquette à l'écran et dans le PNG est peu coûteuse.
