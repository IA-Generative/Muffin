# La voix dans le chat (#517)

Deux fonctions **facultatives, désactivées par défaut** :

- la **dictée** : la personne **enregistre** un message, l'arrête, et obtient le **texte** dans le champ de saisie (modifiable avant l'envoi, jamais envoyé tout seul) ;
- la **lecture à voix haute** : une réponse est lue par une voix de synthèse.

Sans rien configurer, le chat fait ce qu'il a toujours fait : dictée par la reconnaissance du **navigateur** (`SpeechRecognition`, Chrome et Edge seulement) et lecture par la **voix du navigateur** (`speechSynthesis`).
Quand l'administrateur les active (page **Administration → Voix**), les deux passent par un service **compatible OpenAI** — le hub déjà configuré, ou un autre — et **le navigateur reste le repli** si ce service tombe.

> **L'audio et le texte ne sont jamais conservés par Muffin** : ni en base, ni dans le stockage objet, ni dans les journaux (qui n'ont que des tailles, des longueurs, une latence et un code). La clé du service est chiffrée et **jamais relue**.

## Les moteurs

| | Dictée | Lecture |
|---|---|---|
| **Navigateur** (par défaut) | `SpeechRecognition` : sur Chrome, l'audio part chez le fournisseur du navigateur, hors de tout contrôle de l'organisation | `speechSynthesis` : voix du système, aucune sortie |
| **Service compatible OpenAI** | `POST {base}/audio/transcriptions` (Whisper, vLLM, Speaches, LocalAI, faster-whisper-server…) | `POST {base}/audio/speech` (OpenAI, une passerelle, ou le **pod `worker/tts`**) |
| **Adresse** | vide = celle du hub (`OPENAI_API_BASE_URL`) ; sinon une autre, **avec sa propre clé** (la clé du hub n'est jamais envoyée ailleurs) | idem |
| **Modèle** | saisi par l'administrateur (il n'y a pas de sonde simple pour l'audio) | idem, plus une voix, une voix pour l'anglais (facultative) et un format (`mp3`, `wav`, `flac`, `opus`, `aac`) |

L'interface **dit où part la voix** avant d'enregistrer (« envoyée au service de modèles de l'organisation », « au service de transcription de l'organisation », « traitée par votre navigateur »).

### Les réglages (Administration → Voix)

Une adresse, une clé (chiffrée, jamais renvoyée), un modèle, et :

- **dictée** : langue (`auto` — le français de l'interface sert alors d'indice — ou un code), durée maximale (300 s par défaut), poids maximal (25 Mo par défaut) ;
- **lecture** : voix, voix pour l'anglais, format, caractères par demande (4000 par défaut — un texte plus long est lu en plusieurs demandes).

Deux boutons **tester** : la transcription reçoit **une seconde de silence générée par Muffin** (aucun échantillon embarqué), la lecture demande une courte phrase. Le résultat dit le temps mis et, en cas d'échec, un **code** et des mots utilisables (`cle_refusee`, `modele_introuvable` — « ce service ne fournit pas cette fonction ou ne connaît pas ce modèle », `format_refuse`, `moteur_indisponible`…) — jamais le texte du service ni la clé. Un bouton **écouter un exemple** fait entendre la voix par le chemin même du chat.

Un réglage ne peut pas lever les bornes de l'installation (`docs/environment-variables.md`, `VOICE_*`).

## L'API

| Route | |
|---|---|
| `GET /api/voice/status` | pour chaque fonction, `server` ou `browser`, les limites et **où part l'audio** (`hub`, `service`, `browser`) — aucune clé lue, aucun appel |
| `POST /api/transcriptions` | multipart : `file`, `language` (facultatif), `duration_seconds` (facultatif) → `{ text, language, duration_seconds }` |
| `POST /api/speech` | `{ text, language? }` → l'audio (`audio/mpeg`, `audio/wav`…), `Cache-Control: no-store` |
| `GET/PATCH /api/admin/voice`, `POST /api/admin/voice/test-transcription`, `POST /api/admin/voice/test-speech` | **administrateurs** |

Toujours une personne connectée. Les erreurs ont un code qui ne change pas : `404` fonction désactivée, `413` trop lourd / trop long, `415` type refusé, `422` audio vide / langue invalide / texte vide, `429` trop de demandes, `502`/`503`/`504` service en erreur, injoignable ou lent.

### Ce qui est contrôlé avant d'appeler le service

- **Rien n'est appelé avant d'être autorisé** : fonction activée et complète, entrée dans les bornes, limite de débit respectée.
- **Les octets, pas la parole de l'expéditeur** : un enregistrement doit commencer comme l'un des conteneurs que produit un navigateur (WebM, Ogg, MP4/M4A, WAV, MP3, FLAC), et le **type annoncé doit être celui qu'on trouve** (`audio/webm;codecs=opus` pour du WebM…). Un PDF appelé `audio/wav` est refusé ; un type générique (`application/octet-stream`) est accepté si les octets sont de l'audio.
- **Rien n'est décodé par Muffin** : décoder un fichier envoyé par une personne est une surface d'attaque, c'est le travail du service (le hub, un service, un pod sans secret).
- **Plafonds** : poids (limite stricte, jamais plus de 25 Mo), durée (**certaine pour un WAV**, dont l'en-tête la dit ; pour les autres, celle que la page déclare — l'enregistreur s'arrête de lui-même à la durée maximale), texte lu (4000 caractères par demande), et **limite de débit par personne et par minute** (6 transcriptions, 20 lectures ; si elle ne peut pas être vérifiée, on s'arrête avant d'appeler le service : il coûte).
- **Rien du service n'atteint la personne** que le code : pas son texte d'erreur, pas la clé.
- **Ce que le service rend est vérifié** : un audio vide, trop lourd, ou qui n'en est pas un (une page d'erreur HTML) est refusé (`audio_invalide`).

Le texte transcrit est **un message ordinaire** une fois envoyé : les garde-fous d'entrée (#516) s'y appliquent comme à toute saisie.

### La consommation

Chaque transcription ou lecture écrit **une ligne de consommation** (`kind = audio`, étapes `transcription` et `speech`) : **secondes d'audio** et **nombre de caractères**, sans jetons. Écrite au mieux : une consommation qui ne s'écrit pas ne fait pas échouer la transcription.
*Pas encore affichée sur la page « Ma consommation » : les colonnes (`audio_seconds`, `characters`) sont là.*

## Dans la page

- **Dictée serveur** : le bouton micro devient un **enregistreur** — démarrer, **arrêter** (puis « Transcription en cours… », puis le texte **ajouté** au brouillon), **annuler**, durée écoulée sur la durée maximale, **niveau sonore**, arrêt automatique à la durée maximale. Raccourci `Alt+Maj+V` comme avant.
- **Accessibilité** : bouton à bascule (`aria-pressed`), état annoncé par une région `aria-live` (« Enregistrement en cours », « Transcription en cours », « Texte ajouté au message », « Enregistrement annulé »), jamais seconde par seconde ; le clavier reste intact (on peut toujours écrire).
- **Repli** : si le service répond `404` ou `5xx` (injoignable, route absente, en panne), la page dit pourquoi et **utilise la dictée du navigateur pour la suite de la session** quand il en a une ; un enregistrement refusé (trop lourd, trop long…) ne fait pas basculer.
- **Lecture serveur** : la réponse est nettoyée du markdown (comme avant), **découpée en morceaux** (à la fin des phrases) au maximum de caractères réglé, lus l'un après l'autre — le suivant est demandé pendant que le précédent joue. Lire une autre réponse, ou la même une seconde fois, **arrête** la lecture en cours. La **langue** (français ou anglais, d'après les mots courants du texte) choisit la voix ; non reconnue, la voix par défaut. Si le service échoue avant le premier son, la lecture continue avec la voix du navigateur.

## Le pod `worker/tts` (Kitten TTS 2, facultatif)

Un pod qui expose lui-même la route `POST /v1/audio/speech`, modelé sur `worker/vision` (poids épinglés et vérifiés par SHA-256 à la construction de l'image, rien téléchargé à l'exécution, pas de secret, utilisateur non privilégié, **désactivé par défaut**). Muffin n'a **aucun code spécifique** : on donne son adresse interne comme adresse du service de lecture (`http://worker-tts:8080/v1`), un modèle (`kitten-tts-2`) et une voix (`French`). Il rend `wav`, `flac`, `mp3` et `pcm` (**choisir `mp3`** dans l'administration, pas `opus` ni `aac`). Détails, dimensionnement et variables : `worker/tts/README.md`.

**Ni la construction ni la publication de l'image ne sont branchées sur la CI/CD** (`ci.yml`, `cd.yml`) : seuls le lint et les tests du pod le sont. Publier l'image, c'est **distribuer les poids** : à ne faire qu'une fois la licence ci-dessous validée.

> **Français et licence — à lire avant de choisir.**
>
> - Les modèles **Kitten TTS 0.8** (nano 15 M, micro 40 M, mini 80 M ; ONNX, Apache 2.0, très légers) n'ont que **8 voix anglaises** : inutilisables pour des réponses en français. C'est **Kitten TTS 2** (1,7 Md de paramètres, 20 langues dont le français, voix « French ») que le pod sert.
> - Kitten TTS 2 demande **de la mémoire** (de l'ordre de 6 Go de RAM sur CPU) ; la **vitesse de synthèse sur CPU n'a pas été mesurée** (voir `worker/tts/README.md`).
> - Ses poids sont sous la **Stellon Labs Community License** : usage de recherche, non commercial ou commercial limité gratuit ; la gratuité commerciale **s'arrête au-delà de 1 M$ de chiffre d'affaires ou de financement cumulé** ; **obligations d'attribution** à la redistribution des poids, d'un dérivé ou d'un produit qui les embarque (section IV(a) de la licence). **À faire valider par le juridique avant un déploiement.** Le paquet `kittenml` est sous Apache 2.0 et le modèle de locuteur du dossier `speaker/` sous MIT.

## Confidentialité, selon le moteur

| Moteur | Où part ce qui est dit |
|---|---|
| Navigateur | le navigateur (Chrome : son fournisseur, hors du contrôle de l'organisation) |
| Hub (adresse vide) | le service de modèles de l'organisation, avec ses propres règles de conservation |
| Autre service | l'adresse choisie par l'administrateur |
| Pod `worker/tts` | reste dans l'infrastructure : le texte n'est jamais journalisé |

## Pas encore

- **Un modèle de transcription fourni avec Muffin** (le point 3 du ticket : pod `faster-whisper` en int8) : non fait. Aucun code de plus ne serait nécessaire côté Muffin — on donnerait son adresse comme adresse du service de dictée. KittenML publie des modèles de reconnaissance (`kitten-asr-tiny`, `kitten-asr-small-enhanced`) mais **sans fiche de modèle** (format, langues et licence non documentés) : non utilisés.
- **La transcription en direct** pendant la parole : on enregistre, puis on transcrit.
- **Le choix du moteur par personne** : global.
- **La consommation audio sur la page d'usage** : stockée, pas affichée.
- **Le clonage de voix et les balises d'expression de Kitten TTS 2**, le flux audio (la réponse est lue une fois complète, morceau par morceau).
- **Une mesure** de la qualité en français (Word Error Rate des moteurs, latence du pod) : à faire sur un petit corpus avant de choisir un modèle par défaut.
- La durée d'un enregistrement non WAV est celle que la page déclare : un client qui ment sur la durée est borné par le **poids** (25 Mo) et la limite de débit, pas par la durée.
