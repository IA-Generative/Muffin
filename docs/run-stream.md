# Suivi d'un run en direct (#510)

Le chat suit un run (la réponse de l'agent) par un flux **Server-Sent Events** : les étapes s'affichent à l'instant où elles se
produisent et la réponse s'écrit mot à mot. Avant, le front interrogeait le backend toutes les 700 ms (`GET /runs/{id}/events`
puis `GET /runs/{id}`), et le texte n'avançait que par à-coups d'une demi-seconde.

Le flux ne fait que **montrer**. Le run (`GET /runs/{id}`) reste la source de vérité : la réponse finale, les sources et le
statut sont lus sur lui une fois le run terminé, et au moindre problème le chat retombe sur l'interrogation d'avant.

## Le flux

`GET /api/runs/{run_id}/stream` — réservé au propriétaire du run (404 sinon), `Content-Type: text/event-stream`,
`X-Accel-Buffering: no` (nginx ne retient pas les morceaux).

| Événement | Données | Quand |
|---|---|---|
| `step` | un événement du run, comme `GET /runs/{id}/events` : `{id, task_id, type, data, created_at}` | une étape de l'agent |
| `delta` | `{text, replace}` | un morceau de la réponse ; `replace: true` quand le texte envoyé n'est plus la suite de ce qui était affiché (il remplace alors tout) |
| `status` | `{status, current_node, current_activity}` | un changement d'état ; `completed`, `failed`, `cancelled` ou `waiting_for_user` **terminent** le flux |
| `ping` | `{}` | toutes les 15 s au repos |
| `unavailable` | `{}` | Redis ne répond pas : le chat passe à l'interrogation |

Chaque entrée porte un `id` (celui de l'entrée Redis). Un client qui se reconnecte avec `Last-Event-ID` (le navigateur le fait
tout seul) reprend après la dernière qu'il a reçue ; sans, il reçoit **tout le flux depuis le début** : c'est ce qui permet à une
page rechargée en plein run de retrouver ses étapes et le début de la réponse.

## Comment ça circule

- L'agent tourne dans le processus du backend. Chaque étape (`POST /internal/runs/{id}/events`), chaque changement de statut et
  chaque morceau de réponse est écrit dans un **Redis Stream** par run (`run:{id}:stream`), après l'écriture en base.
- La route lit ce flux (`XREAD` bloquant) : elle peut tourner sur **un autre pod** que celui qui exécute l'agent, c'est Redis qui
  les relie. Le client Redis est asynchrone (`redis.asyncio`) pour ne pas bloquer la boucle d'événements.
- Les morceaux de réponse sont le **texte décodé** du champ `answer` du JSON que le modèle écrit (pas le JSON), regroupés par
  50 ms au plus.
- Tout est **au mieux** : publier ne fait jamais échouer un run ni une requête (délai d'une seconde, erreur journalisée). Un
  flux muet n'arrête pas le suivi : toutes les 15 s la route regarde le statut réel en base, ce qui termine aussi un run qu'un
  pod tombé n'a pas pu terminer (le balayeur le marque `failed`).
- Le flux garde 20 000 entrées au plus et expire 15 minutes après la dernière écriture.

## Du côté du chat

`useChat.ts` ouvre un `EventSource` (avec le cookie de session) par run en cours. Il passe à l'**interrogation** de l'ancien
mode, depuis l'état où en est le run, quand :

- le serveur refuse le flux (non connecté, run introuvable, trop de flux ouverts : 429) ;
- la connexion échoue trois fois de suite sans rien recevoir ;
- rien n'arrive pendant 45 s (un `ping` arrive toutes les 15 s) ;
- le serveur envoie `unavailable` ;
- le navigateur n'a pas `EventSource`, ou `VITE_DISABLE_RUN_STREAM=true` a été fixé au build.

## Réglages

`RUN_STREAM_TTL_SECONDS`, `RUN_STREAM_MAXLEN`, `RUN_STREAMS_PER_USER`, `RUN_STREAM_PING_SECONDS` (backend) et
`VITE_DISABLE_RUN_STREAM` (frontend) — voir `environment-variables.md`.

Derrière nginx, `proxy-read-timeout: 600` (déjà réglé dans `helm/values/common-values.yaml`) suffit pour une réponse ; le
`X-Accel-Buffering: no` de la réponse règle le buffering sans changer le chart. Un autre proxy doit laisser passer
`text/event-stream` sans mise en mémoire tampon ni compression.

## Mesures

Backend réel (uvicorn) et front réel, un agent simulé qui publie dans Redis depuis un autre processus (donc le chemin entre
pods est exercé) :

- **Délai entre la publication d'un mot dans Redis et son affichage dans la page** : médiane 5 ms, maximum 9 ms (20 mots).
  Avant, d'après les constantes du code : entre 0,4 s (publication du texte partiel) et 1,1 s (plus un tour d'interrogation).
- **Requêtes pour suivre une réponse** : une requête longue plus une lecture finale du run, quelle que soit sa durée. Avant :
  deux requêtes toutes les 0,7 s, soit environ 3 par seconde (une réponse de 20 s : une soixantaine).
- **Repli** : avec le flux refusé (404), la réponse s'affiche toujours, par l'interrogation d'avant.

## Limites

- Chaque message en cours garde une connexion ouverte : `RUN_STREAMS_PER_USER` la borne par utilisateur **et par pod** (pas de
  compteur partagé entre pods). Au-delà, `429` et l'interrogation prend le relais.
- Le texte de la réponse passe par Redis pendant 15 minutes (le texte partiel y passait déjà, 10 minutes). Un compte qui lit
  Redis le voit : l'accès à Redis reste à réserver aux services.
- Le flux montre l'agent d'un run, pas son état définitif : une réponse n'est « terminée » pour le chat qu'une fois lue sur le
  run.
