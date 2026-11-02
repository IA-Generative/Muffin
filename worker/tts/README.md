# worker/tts — synthèse vocale (Kitten TTS 2), facultatif

Un pod **facultatif, désactivé par défaut** qui lit un texte à voix haute et l'expose par une **route compatible OpenAI** (`POST /v1/audio/speech`). Muffin n'a **aucun code spécifique** pour lui : dans *Administration → Voix → Lecture à voix haute*, on donne son adresse interne comme adresse du service (`http://worker-tts:8080/v1` en Compose, `http://muffin-tts:8080/v1` dans le chart), le modèle `kitten-tts-2` et la voix `French`. Voir `docs/voice.md`.

Il est modelé sur `worker/vision` : **poids épinglés par révision et vérifiés par SHA-256 à la construction de l'image**, **rien n'est téléchargé à l'exécution** (`HF_HUB_OFFLINE=1`), aucun secret, utilisateur non privilégié, système de fichiers en lecture seule.

> ## ⚠️ Licence des poids — à valider avant tout déploiement
>
> Les poids de **Kitten TTS 2** sont sous la **Stellon Labs Community License** (`LICENSES.md`, et le fichier `LICENSE.md` du modèle est **dans l'image**) : usage de recherche, non commercial ou commercial limité **gratuit** ; la gratuité commerciale **s'arrête au-delà de 1 M$ de chiffre d'affaires annuel ou de financement cumulé** ; **obligations d'attribution** (section IV(a)) quand on distribue les poids, un dérivé ou un produit qui les embarque — y compris, **en construisant et en publiant cette image**. Le paquet `kittenml` est sous Apache 2.0 ; `speaker/` (modèle de locuteur) sous MIT ; le codec audio `s3gen` (ResembleAI/chatterbox-turbo) sous MIT. **Faites valider par le juridique avant de construire, publier ou déployer l'image.**

## Pourquoi Kitten TTS 2 et pas les modèles 0.8

Les modèles légers **Kitten TTS 0.8** (nano 15 M, micro 40 M, mini 80 M ; ONNX ; Apache 2.0) n'ont que **8 voix anglaises**. Pour des réponses **en français** il faut **Kitten TTS 2** (1,7 Md de paramètres, 20 langues, voix « French »). C'est plus lourd — voir le dimensionnement.

## La route

| Route | |
|---|---|
| `POST /v1/audio/speech` | `{ model, input, voice, response_format, speed }` → l'audio |
| `GET /v1/models` | le modèle servi (pour les outils compatibles OpenAI) |
| `GET /v1/audio/voices` | les noms des voix (non standard) |
| `GET /health` | `200` une fois le modèle chargé, `503` avant ; jamais d'authentification |

- `input` : obligatoire, au plus `TTS_MAX_CHARS` caractères (le backend de Muffin découpe de toute façon à la longueur réglée dans l'administration).
- `voice` : un nom de la liste, sans tenir compte de la casse ; à défaut, `TTS_DEFAULT_VOICE` (`French`). Une voix inconnue est refusée (`422`).
- `model` : accepté, quelle que soit sa valeur.
- `response_format` : **`wav` (défaut), `flac`, `mp3`, `pcm`** (échantillons bruts 16 bits little-endian, 24 kHz). **Pas `opus` ni `aac`** : choisissez `mp3` dans l'administration de Muffin. L'encodage MP3 a été vérifié dans l'image (libsndfile 1.2.2).
- `speed` : 0,5 à 2,0. **Le modèle n'a pas de réglage de vitesse** : c'est un étirement temporel (vocodeur de phase) après coup — les artefacts grandissent avec le facteur.
- Les voix dont le nom est celui d'une personne sont **anglaises** ; les autres sont nommées d'après leur langue (`French`, `SpanishAbuela`…). Pour toute voix non anglaise, la normalisation de texte du modèle (réglée pour l'anglais) est **désactivée** : elle abîmerait les nombres et les dates.
- Erreurs au format OpenAI (`{"error": {"message", "type", "code"}}`) : `401` clé, `413` texte trop long, `422` demande invalide, `429` **toutes les places sont prises** (avec `Retry-After`, pas de file d'attente qui gonfle), `503` modèle pas encore chargé, `504` délai dépassé.
- **Le texte lu n'est jamais journalisé** : le journal n'a que des longueurs, la voix et des durées.

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `TTS_API_KEY` | si définie, `/v1/*` exige `Authorization: Bearer <clé>` (comparaison à temps constant) ; sinon ouvert — c'est un service **interne**, à ne pas exposer | vide |
| `TTS_MAX_CHARS` | longueur maximale de `input` | `4000` |
| `TTS_MAX_CONCURRENCY` | synthèses simultanées ; au-delà, `429` | `1` |
| `TTS_REQUEST_TIMEOUT_SECONDS` | délai d'une demande (`504` au-delà) | `120` |
| `TTS_DEFAULT_VOICE` | voix par défaut | `French` |
| `TTS_TORCH_THREADS` | fils de calcul de PyTorch (à régler sur la demande de CPU du pod) | défaut de PyTorch |
| `TTS_RETRY_AFTER_SECONDS` | valeur du `Retry-After` du `429` | `5` |
| `TTS_WEIGHTS` | variante des poids : `packed` (954 Mo, **sans perte**, défaut) ou `emb4` (469 Mo, **avec perte** sur l'embedding) | `packed` |
| `TTS_DECODER`, `TTS_MODEL_DIR`, `TTS_MODEL_NAME` | réglages internes de l'image (décodeur, dossier des poids, nom du modèle) | ceux de l'image |

La variante des poids est celle **embarquée** par l'image : `docker build --build-arg WEIGHTS=emb4 …` pour l'autre (le `weights.sha256` vérifie l'une ou l'autre).

## Dimensionnement

- **Mémoire** : prévoir **de l'ordre de 6 Go** (le chart demande 6 Gi et limite à 8 Gi ; Compose limite à 8 Go). Le modèle est chargé **une fois**, au démarrage.
- **Image** : environ **6 Go** (2,1 Go de poids, 1,6 Go d'environnement Python avec PyTorch **CPU**).
- **Démarrage** : le pod répond `503` sur `/health` tant que le modèle n'est pas chargé ; sur la machine d'essai (30 Go de RAM) il est devenu sain en **moins de 4 minutes** (la sonde de démarrage attend 5 minutes). Sur un processeur plus lent, prévoyez plus.
- **CPU** : une synthèse occupe les cœurs donnés à PyTorch ; une seule à la fois par défaut. **Pas de mise à l'échelle à zéro** (le chart n'en a pas) : une lecture est interactive, et un pod à zéro ferait attendre le chargement du modèle.

> **Non mesuré.** Je n'ai pas de mesure du **temps de synthèse** ni du **facteur temps réel** sur CPU : l'essai réel a été interrompu avant d'en produire. À mesurer sur la machine cible avant de s'engager sur une expérience utilisateur (un texte long est lu **morceau par morceau** par la page, le morceau suivant étant demandé pendant que le précédent joue — ce qui ne marche que si une synthèse va plus vite que la lecture). Si elle est plus lente que le temps réel, préférez un service plus rapide (le hub, un GPU) ou le repli sur la voix du navigateur.

## Lancer

```bash
# Compose : le service est dans le profil « tts » (rien ne le démarre par défaut)
docker compose --profile tts up -d worker-tts     # construit l'image (longue) puis démarre
# Chart Helm : tts.enabled: true (voir helm/README.md)
```

Dans l'administration de Muffin : adresse `http://worker-tts:8080/v1`, modèle `kitten-tts-2`, voix `French`, format `mp3`, et une clé **quelconque** (Muffin en exige une pour toute adresse autre que celle du hub) — qui n'a de sens que si `TTS_API_KEY` est définie dans le pod.

## Tests

```bash
cd worker/tts && uv sync --group test && uv run pytest && uv run ruff check .
```

Les tests utilisent un **faux moteur** (une sinusoïde) : ni PyTorch ni le modèle ne sont chargés. Aucun test ne charge le vrai modèle : la synthèse réelle n'est **pas** couverte par la suite automatique.

## Confidentialité

Le texte reste **dans l'infrastructure** : le pod n'a besoin d'aucun réseau sortant à l'exécution (tout est dans l'image), n'a aucun secret, et ne journalise pas ce qu'il lit. L'interface de Muffin le dit à la personne (« le texte est envoyé au service vocal de l'organisation »).

## Ce qui n'est pas fait

- le **clonage de voix** et les **balises d'expression** de Kitten TTS 2 (`[joyful]`, `<laugh>`…) ;
- le **flux audio** (l'audio est rendu en entier, par morceaux de texte côté page) ;
- les formats `opus` et `aac` ;
- la **voix d'un utilisateur** ou par assistant : une voix pour le français, éventuellement une pour l'anglais, réglées globalement.
