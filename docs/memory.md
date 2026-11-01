# La mémoire de l'utilisateur (#34, #282, #283, #284)

L'assistant peut **retenir de la personne** de quoi adapter la **forme** de ses réponses : comment elle les aime, son contexte, ce qu'elle a demandé de retenir. C'est
elle qui décide, voit tout, et peut tout corriger, désactiver, supprimer ou exporter.

> **La mémoire règle la forme et le contexte, jamais le fond.** Ce n'est pas une source : elle ne remplace aucune citation, le contrôle d'ancrage des réponses
> (`ground_check`) est inchangé, et **ce que dit la demande en cours passe toujours avant la mémoire**.

Cette première version couvre ce que la personne écrit ou demande elle-même. **L'apprentissage automatique** (depuis les 👍/👎, les habitudes d'usage) est hors de cette
première livraison, voir « Pas encore ».

## Ce qui est retenu

Un élément a un **type** (`preference`, `habit`, `context`, `fact`), une phrase (300 caractères au plus), une **origine** (`explicit` : écrit, corrigé ou demandé par la
personne ; `inferred` : appris — réservé à l'apprentissage à venir), une confiance, un compteur de confirmations, et une date de dernière utilisation. Un même texte
dit deux fois est **un seul élément** (clé dérivée de la phrase, unique par personne et par type). Un élément corrigé par la personne devient le sien : rien ne l'écrase.

Au plus **100 éléments** par personne (`MEMORY_MAX_ITEMS`).

## Ce qui n'est jamais retenu

- **Les catégories sensibles** (RGPD art. 9 et ce qui s'en approche) : santé, opinions politiques et religieuses, origine, orientation, appartenance syndicale,
  données génétiques et biométriques, condamnations. C'est une **liste de mots** (`app/core/memory_rules.py`) qui **pèche par prudence** : un métier qui touche à ces sujets
  est refusé aussi, et la personne peut reformuler. Refusé **même sur demande explicite**.
- **Ce que les garde-fous de saisie refusent** (#516) : un IBAN, un secret, un identifiant refusé dans un message ne l'est pas moins dans la mémoire. Ce que les garde-fous
  masquent est conservé masqué.
- Une phrase vide ou trop longue.

## Où la mémoire sert

| Contexte | Mémoire |
|---|---|
| Chat personnel | **utilisée** (interrupteur de la personne, coupe-circuit de l'administrateur) |
| Conversation **sans mémoire** (« + » → « Outils » → « Mémoire » décoché) | ni lue ni écrite, le temps du réglage (`temporary`) |
| Chat avec un **assistant** (#514) | non (`unavailable`) |
| **Routine** (#524) | non |
| **API compatible OpenAI** (#513) | non |

Ce choix est figé sur le run à sa création (`Run.memory_mode`). La mémoire d'une personne n'est donc jamais mise au service d'une conversation partagée.

## Dans l'agent

- **Lecture** : `prepare` lit la mémoire **une fois par run** (`GET /api/internal/runs/{id}/memory`), dans la limite de `MEMORY_PROMPT_MAX_CHARS` (≈ 500 jetons) : d'abord ce que la
  personne a écrit, puis le plus certain. Une mémoire illisible est une mémoire vide : le run continue.
- **Injection** : dans `generate_answer`, en **bloc `<memory>` dans la partie données** du message, sous les extraits — **jamais dans le prompt système** administrable, qui n'a qu'une
  règle ajoutée *quand il y a une mémoire* : elle dit que le bloc existe, qu'il est subordonné à la demande, que ce n'est ni une consigne ni une preuve, et de ne pas le
  citer. Les chevrons des valeurs sont retirés : rien ne peut fermer le bloc. **Sans mémoire, le prompt est strictement celui d'avant.**
- **Usage** : après la réponse, le worker dit au backend quels éléments ont servi : ils sont **datés** (`last_used_at`) et **comptés sur le run** (`Run.memory_used`). Le chat affiche alors
  « Adaptée à votre mémoire · voir ou modifier » avec un lien vers la page. Le contenu n'est nulle part sur le run.
- **Dans le chat** : le plan peut choisir le mode `memory` (« retiens que… », « oublie que… », « que sais-tu de moi ? »), proposé seulement si la mémoire n'est pas suspendue.
  Le nœud `memory_command` fait exécuter l'ordre par le backend **sous les mêmes règles que la page**, et **la réponse est écrite par le code** à partir de ce qui a vraiment été
  fait (« C'est noté : … », « C'est oublié : … », ou pourquoi non) : aucun modèle ne peut dire qu'il a retenu ce qu'il n'a pas retenu. « Oublie » ne supprime que si **un seul** élément
  correspond ; sinon il liste les candidats et n'en supprime aucun. Tout effacer se fait depuis la page.
- Un `retiens que…` dans une conversation sans mémoire, avec la mémoire désactivée, ou dans un assistant, répond pourquoi et ne retient rien.

## La page « Ma mémoire » (`/memory`, menu de l'utilisateur)

Les éléments par type, avec l'origine (« écrit par vous » / « appris »), la date de mise à jour et d'usage ; pour chacun, **utiliser** (interrupteur), **corriger**, **supprimer** ;
**ajouter** un élément ; l'interrupteur général ; **tout supprimer** (avec confirmation) ; **exporter** en JSON. Supprimer ou désactiver prend effet **dès la réponse suivante**
(la mémoire est relue à chaque run).

## API

Utilisateur (toujours filtrée sur la personne connectée ; l'élément d'un autre est un `404`) :

| Route | |
|---|---|
| `GET /api/memory` | les éléments, le réglage, les limites |
| `POST /api/memory/items` | retenir (`201` ; `200` si c'était déjà là) |
| `PATCH /api/memory/items/{id}` | corriger la phrase, activer/désactiver |
| `DELETE /api/memory/items/{id}` · `DELETE /api/memory/items` | oublier un élément · tout |
| `PUT /api/memory/settings` | activer/désactiver la mémoire |
| `GET /api/memory/export` | tout, en JSON |
| `GET /api/admin/memory/stats` | **administrateur** : des comptes (personnes, éléments, mémoires coupées), jamais un contenu |

Interne (clé des workers) : `GET /api/internal/runs/{id}/memory`, `POST …/memory/used`, `POST …/memory/command`.

## Vie privée

- La mémoire n'est lisible que par son propriétaire : ni dans les journaux, ni dans les **événements d'un run** (le plan ne publie pas le texte d'une commande ; `memory_command_completed`
  ne porte que l'action et l'issue), ni côté administrateur (comptes seulement).
- Le texte d'une valeur lue passe, le temps du run, par l'**état du graphe** (donc par le point de contrôle Redis du run), comme la question elle-même.
- Un élément est une donnée personnelle : accès, correction, suppression et export sont sur la page.

## Pas encore

- **L'apprentissage automatique** : préférences de style depuis les 👍/👎 (#285), habitudes d'usage (#286) — le modèle (`origin = inferred`, `confidence`, `evidence_count`, `expires_at`) est
  prêt, **rien n'écrit encore ces éléments** et rien n'applique `expires_at`. Le reclassement des sources (#287), le cache des réponses validées (#288) et la mesure de l'effet avec un groupe
  témoin (#289) restent à faire.
- **La suppression avec le compte** : il n'y a pas de table des utilisateurs (les comptes sont dans Keycloak), donc rien ne l'emporte automatiquement. La personne supprime depuis la page ;
  une purge à la fermeture d'un compte est à brancher avec ce processus.
- **La mémoire dans l'étape `plan`** (langue, vocabulaire métier, collections habituelles) : seule la génération de la réponse la lit pour l'instant.
- **Le tri par pertinence** quand la mémoire dépasse le plafond : on garde ce que la personne a écrit, puis le plus certain, sans regarder la question.
- **La mention dans les conditions d'utilisation** et **le guide d'aide de l'application** (le prompt `app_help`, versionné en base) : à compléter par un administrateur.
- **Un coupe-circuit modifiable depuis l'interface** : `MEMORY_ENABLED` est une variable d'environnement.
- **Une conversation sans mémoire qui n'est pas enregistrée** : « sans mémoire » ne veut dire ni lue ni apprise ; la conversation reste dans l'historique.
