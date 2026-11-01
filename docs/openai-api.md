# L'API compatible OpenAI (#513)

Muffin répond au format de l'API de chat d'OpenAI : `GET /v1/models` et `POST /v1/chat/completions`. Tout client qui parle
« OpenAI » (le SDK `openai`, Open WebUI, Continue, LibreChat, n8n…) peut donc discuter avec Muffin et obtenir une **réponse
rédigée par l'agent, citée et vérifiée**, limitée aux collections que **le propriétaire de la clé** peut lire. Le serveur MCP
(`mcp.md`) fait autre chose : il ne renvoie que des sources, et c'est le modèle du client qui rédige.

## S'authentifier

Une **clé d'API personnelle** de portée `chat` (`api-keys.md`, menu utilisateur → *Clés d'API*), dans `Authorization: Bearer sk-muffin-…`.
Rien d'autre n'est accepté : ni le cookie de session (un navigateur l'enverrait à n'importe quelle page), ni un jeton Keycloak.

| Cas | Réponse |
|---|---|
| Pas de clé, clé inconnue, révoquée, expirée, ou d'une autre portée | `401` (toujours la même, sans dire pourquoi) |
| Plus de 120 requêtes par minute avec la même clé | `429` + `Retry-After` |
| Clés d'API désactivées (pas de `API_KEY_PEPPERS`) | `503` |

Les erreurs ont le format d'OpenAI : `{"error": {"message", "type", "code", "param"}}`.

## Les modèles

Un « modèle » est une **portée de recherche**, pas un LLM : le modèle de langage utilisé reste celui choisi par Muffin.

- `muffin` : toutes les collections lisibles par le propriétaire de la clé (l'agent choisit lesquelles consulter) ;
- `muffin:collection:<id>` : une collection et ses sous-collections, **et rien d'autre** : l'agent ne peut pas aller chercher dans les autres collections du propriétaire (`Run.scope_locked`). Une collection que le propriétaire ne peut pas lire n'existe pas
  pour lui (`404`, `model_not_found`).

`GET /v1/models` liste `muffin` et les collections de premier niveau lisibles (100 au plus, `OPENAI_API_MAX_LISTED_COLLECTIONS`).
Chaque modèle porte, en plus des champs d'OpenAI, un `name` à afficher.

## Une conversation

```bash
curl https://muffin.example/v1/chat/completions \
  -H "Authorization: Bearer $MUFFIN_KEY" -H "Content-Type: application/json" \
  -d '{"model": "muffin", "messages": [{"role": "user", "content": "Combien de jours de télétravail ?"}]}'
```

```python
from openai import OpenAI

client = OpenAI(base_url="https://muffin.example/v1", api_key="sk-muffin-…")
answer = client.chat.completions.create(
    model="muffin", messages=[{"role": "user", "content": "Combien de jours de télétravail ?"}]
)
print(answer.choices[0].message.content)
```

- **Le dernier message doit être de l'utilisateur** : c'est la question. Les messages `user` et `assistant` qui le précèdent sont
  l'historique de la conversation que lit l'agent. Les messages `system` et `developer` sont **ignorés** : l'agent a ses propres
  consignes. Au plus 40 messages de 20 000 caractères. Le contenu est du texte (les images ne sont pas prises en charge).
- **`stream: true`** : flux SSE au format OpenAI (`chat.completion.chunk`, puis `data: [DONE]`). Avec
  `stream_options.include_usage`, un dernier morceau porte `usage`.
- **Refusés (`400`, `unsupported_parameter`)** : `tools`, `functions`, `tool_choice`, `function_call`, `response_format`,
  `logprobs`, `top_logprobs`, `n` différent de 1. Plutôt que d'être ignorés sans un mot.
- **Acceptés et sans effet** : `temperature`, `max_tokens`, `max_completion_tokens` (l'agent règle lui-même la rédaction).
- **Sans question à poser** : un appel est un programme, personne ne peut répondre à une question de clarification (`ask_user`) ;
  l'agent répond du mieux qu'il peut. Les propositions de modification de document ne sont pas exposées.

### Les citations

Les repères `[id]` du texte sont remplacés par des numéros `[1]`, `[2]`… dans l'ordre où l'agent les cite, et une liste **Sources** est
ajoutée à la fin du texte, pour les clients qui n'affichent que du texte. Un champ non standard `sources` (`index`, `id`, `name`,
`page`, `url`, `excerpt`) porte la même chose pour ceux qui savent le lire ; `url` ouvre le document dans Muffin. Dans le flux, il est
dans le morceau qui porte `finish_reason`.

### Les étapes de l'agent

Dans le flux, avec `"muffin": {"steps": true}` (c'est `extra_body={"muffin": {"steps": True}}` dans le SDK), les étapes (« Recherche
dans les collections »…) arrivent dans `delta.reasoning_content`, **jamais** dans le texte de la réponse. Sans cela, elles ne sont pas
envoyées.

### Les conversations

Chaque appel crée une conversation marquée « API » : elle appartient à l'utilisateur, **n'apparaît ni dans la barre latérale ni dans la
recherche**, et elle est purgée après 7 jours (`OPENAI_API_RETENTION_DAYS`). Pour poursuivre une **vraie** conversation de Muffin, on
passe son id dans l'en-tête `X-Muffin-Conversation` (ou `"muffin": {"conversation_id": "…"}`) : seule la dernière question est alors lue,
l'historique est celui de la conversation. Celle d'un autre utilisateur répond `404`.

La réponse porte aussi `muffin.run_id` et `muffin.conversation_id`.

## Limites

- Au plus 3 réponses en cours par utilisateur et par pod (`OPENAI_API_RUNS_PER_USER`), sinon `429`.
- Une requête sans réponse après 540 s est annulée (`504`, `OPENAI_API_TIMEOUT_SECONDS` ; l'ingress coupe à 600 s).
- Si le client coupe la connexion, le run est **annulé**.
- Un run qui échoue répond `502` (`run_failed`) sans dire pourquoi : le détail est dans les journaux du serveur.
- Un run lancé par une clé n'a pas de jeton Keycloak : les outils de l'agent qui appellent un service au nom de l'utilisateur avec ce
  jeton (`app/agent/user_token.py`) n'en disposent pas.

## Dans Open WebUI

*Réglages → Connexions → API OpenAI* : l'URL `https://muffin.example/v1` (dans docker : `http://backend:8000/v1`) et la clé. Open WebUI
liste les modèles de Muffin et discute avec eux. Muffin y est un modèle comme un autre : les outils de connaissances d'Open WebUI ne
s'appliquent pas à lui, c'est l'agent de Muffin qui cherche.

## Sécurité

- La clé représente son propriétaire, **jamais un administrateur**. Ses groupes Muffin sont relus à chaque appel (`api-keys.md`).
- Une collection interdite au propriétaire n'est ni listée, ni utilisable comme modèle, ni citée.
- Le secret n'est jamais journalisé ni renvoyé après sa création.
