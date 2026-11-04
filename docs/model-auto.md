# Mode Auto : le choix du modèle

Quand la personne ne choisit pas de modèle (c'est le réglage par défaut du chat, « Auto »), l'agent **choisit lui-même** le modèle de la réponse selon la
difficulté de la demande : un modèle léger pour une salutation ou une question simple, un modèle puissant pour une analyse longue. Un modèle choisi à la main
dans le sélecteur est utilisé tel quel.

## Ce que règle l'administrateur

Page **Administration → Modèles et mode Auto** (`/admin/models`), pour chaque modèle du hub :

- un **score de 0 à 100** : la difficulté des tâches qu'il traite bien (0 trivial, 100 très complexe). Sans évaluation, un modèle vaut 50 ;
- une **description** : ce qu'il fait correctement, en ses mots. Le classifieur la lit pour départager des modèles ;
- un interrupteur **utilisable en mode Auto** (un modèle désactivé reste choisissable à la main) ;
- le **modèle de classification** (global) : par défaut le moins puissant des modèles utilisables, puisqu'il est appelé à chaque message.

Les **capacités** (`chat`, `vision`, `embeddings`, `image_generation`, `speech_to_text`, `text_to_speech`) sont **calculées par le backend** et affichées en
étiquettes, jamais modifiables : chat, vision et embeddings sont trouvés par essai sur le hub (mis en cache comme la liste des modèles), les autres viennent
des réglages image et voix. Seuls les modèles de conversation reçoivent un score ; les autres ne sont jamais choisis.

## Comment le choix est fait

Le nœud `route_model` du graphe (entre `prepare_request` et `plan`, voir `docs/agent-execution-graph.md`) :

1. lit les candidats : modèles de conversation utilisables en Auto, du moins au plus puissant (`GET /api/internal/llm/auto-candidates`) ;
2. un appel JSON court au classifieur renvoie `level` (0-100), `complexity`, `intent` et, si la description d'un modèle correspond clairement, `preferred_model` ;
3. **en code** : le modèle choisi est le moins puissant dont le score couvre le niveau (le préféré s'il le couvre aussi). Aucun ne le couvre : le plus puissant.
   Avec des images, les modèles qui lisent les images passent d'abord ;
4. le modèle devient `chat_model` pour tous les appels du run, est gardé sur le run (`routing`) et écrit dans l'événement `model_routed` ; le chat l'affiche
   sous la réponse (« Modèle : … »).

Rien ne fait échouer un run : aucun modèle évalué, classifieur en erreur ou réponse illisible, et le modèle par défaut (le premier du hub) est gardé. Avec un seul
candidat, il n'y a pas d'appel de classification.

## API

| Route | Rôle |
|---|---|
| `POST /api/runs` | champ `model` : absent ou `auto` pour le mode Auto, sinon l'identifiant du modèle |
| `GET /api/admin/models` | modèles du hub, capacités, score, description, modèle de classification (admin) |
| `PUT /api/admin/models/{id}` | `{score, description, auto_enabled}` (admin) |
| `PUT /api/admin/models/classifier` | `{classifier_model}` (admin) |
| `GET /api/internal/llm/auto-candidates` | pour l'agent |
