# La mémoire de l'utilisateur (#34, #282, #283, #284)

L'assistant peut **retenir de la personne** de quoi adapter la **forme** de ses réponses : comment elle les aime, son contexte, ce qu'elle a demandé de retenir. C'est
elle qui décide, voit tout, et peut tout corriger, désactiver, supprimer ou exporter.

> **La mémoire règle la forme et le contexte, jamais le fond.** Ce n'est pas une source : elle ne remplace aucune citation, le contrôle d'ancrage des réponses
> (`ground_check`) est inchangé, et **ce que dit la demande en cours passe toujours avant la mémoire**.

Cette version couvre ce que la personne écrit ou demande elle-même, **les préférences de style apprises de ses 👍/👎** (#285) et **les collections qu'elle consulte le plus** (#286).

## Ce qui est retenu

Un élément a un **type** (`preference`, `habit`, `context`, `fact`), une phrase (300 caractères au plus), une **origine** (`explicit` : écrit, corrigé ou demandé par la
personne ; `inferred` : appris de ses 👍/👎, voir plus bas), une confiance, un compteur de confirmations, et une date de dernière utilisation. Un même texte
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

## Ce qui s'apprend des 👍/👎 (#285)

**Sans modèle** : des règles (`app/core/style_signals.py`), pas d'appel de LLM, donc aucun coût et un résultat reproductible. Deux dimensions de style : la **longueur** (concis / détaillé) et le
**tableau** (en tableau / pas de tableau). Chaque feedback donne des **signaux** :

| Signal | Poids |
|---|---|
| Ce que la personne **dit** dans le commentaire (« trop long », « plus court », « trop court », « pas assez détaillé », « en tableau », « pas de tableau »…) — lu sans casse ni accents, une négation (« pas trop long ») n'en est pas un | 1 |
| 👍 sur une réponse **courte** (< 700 caractères) → concis ; **longue** (> 2000) → détaillé ; avec un **tableau** → tableau | 0,4 |
| 👎 « pas utile » sur une réponse **longue** → concis | 0,4 |

Un 👎 pour le ton, l'exactitude ou les sources, **sans commentaire, n'apprend rien du style** : sans modèle, on ne sait pas dans quel sens le corriger.

- **Pas de sur-apprentissage** : un signal pèse la moitié tous les 30 jours (`MEMORY_LEARNING_HALF_LIFE_DAYS`) ; une préférence n'existe qu'au-delà de **1,5** — deux commentaires qui concordent, ou un
  commentaire et deux mesures — jamais un vote seul. Des signaux contraires s'annulent ; assez de signaux dans l'autre sens retournent la préférence.
- **Recalculé, pas ajusté** : à chaque feedback, les préférences sont recalculées depuis les feedbacks des 90 derniers jours (le dernier de chaque message compte : changer d'avis remplace). Un
  feedback changé ou disparu n'est donc plus dans la somme, et ce qui n'est plus confirmé disparaît. Fait **dans la requête du feedback** : la question suivante l'a déjà. Un échec ne fait jamais
  échouer le feedback.
- Les éléments appris sont `origin = inferred`, ont une confiance (|score|/3) et une **échéance** (`MEMORY_LEARNED_TTL_DAYS`, 45 jours, renouvelée à chaque recalcul) : passé ce délai ils ne sont plus
  lus. Ils sont **dits par une phrase fixe** (« Préfère des réponses concises »…) : **le texte d'un commentaire n'est jamais gardé**.
- **Jamais sur ce que la personne a écrit** (un élément `explicit` de la même clé n'est pas touché), **jamais mémoire désactivée**, ni à partir d'une conversation où elle n'était pas utilisée
  (sans mémoire, assistant). Un élément appris que la personne **désactive** reste désactivé ; un élément appris qu'elle **supprime** — ou « tout supprimer » — **ne revient pas** : les feedbacks
  donnés jusque-là ne comptent plus (`learning_from`).
- Interrupteur propre à l'apprentissage : `MEMORY_LEARNING_ENABLED`.

## Les collections habituelles (#286)

**Comptées, sans modèle.** À la fin de chaque réponse, le backend compte ce qu'elle a utilisé (`HabitService.record_run`, après l'enregistrement du résultat ; un échec ne fait jamais échouer la réponse) :

| Usage | Poids |
|---|---|
| une collection **citée** par la réponse (`citations[].vdb_id`, `cited`) | 1 |
| une collection **attachée** par la personne, pour une réponse qui s'appuie sur quelque chose (au moins une citation) | 0,5 |

Un score se **tasse de moitié tous les 30 jours** (`MEMORY_LEARNING_HALF_LIFE_DAYS`) et s'incrémente à chaque réponse. **Une collection n'est une habitude qu'à partir de 1,8** (deux réponses qui la citent à quelques jours d'écart, ou
quatre où elle était attachée) : un seul usage ne retient rien. Sous 0,25, elle est oubliée ; au plus `MEMORY_HABITS_MAX` (10) sont gardées, les plus lourdes. Compté **seulement** pour une mémoire en usage (pas
sans mémoire, assistant, routine, API, mémoire coupée), jamais pour une demande bloquée par les garde-fous, jamais sur ce que la personne a écrit, jamais la collection temporaire d'une conversation.

Chaque habitude est un élément `habit` (« Consulte souvent la collection « Règlements » ») : la personne le voit, le désactive, le supprime. Le score et la collection sont dans `data` (jamais dans un prompt : **une habitude n'est pas donnée au
modèle qui écrit la réponse**, seulement au routage). Ce qu'elle **supprime** ne revient pas avec ce qu'elle a fait avant (`learning_from`) : il faut de nouveaux usages.

**Jamais une collection qu'elle ne peut pas lire.** À chaque lecture (page, routage, sélecteur), une collection supprimée ou dont l'accès a été retiré est **oubliée**, et le nom affiché est celui d'aujourd'hui.

**Dans le routage** — un *a priori*, jamais un filtre :

- les collections habituelles sont **en tête du catalogue** du plan et marquées `habitual: yes` ; le plan est prévenu (seulement s'il y en a, donc sinon son prompt est celui d'avant) que c'est un **départage** à pertinence comparable : jamais une raison en soi, jamais ce
  qui écarte une collection qui convient mieux ;
- au-delà de 20 collections, le **pré-filtre vectoriel** compte une habitude **jusqu'à 10 % de plus** (`score × (1 + 0,1 × poids)`) : il demande quelques candidats de plus et recoupe aux 20 meilleurs, de sorte qu'une habitude presque aussi proche passe,
  et qu'une habitude nettement moins pertinente ne déloge rien. Les collections attachées restent toujours dans le catalogue ;
- rien ne sort du périmètre `accessible_vdbs`, et une question hors habitudes trouve la bonne collection comme avant.

**Dans le sélecteur** du composer (« + » → « Collections »), les collections habituelles sont en premier, avec la mention « habituelle » (`GET /api/memory/habits`) ; rien n'est retiré de la liste.

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

- **Les sujets récurrents** (les tags des documents cités) du ticket #286 : pas faits — sans usage défini (rien ne les consommerait, ni le routage ni la réponse), ils ne seraient qu'un encombrement de la page. Le routage
  ne se sert que des collections.
- **Le reclassement des sources** (#287), le cache des réponses validées (#288) et la mesure de l'effet avec un groupe témoin (#289) restent à faire.
- **Le commentaire libre lu par un modèle** (#285 le proposait) : volontairement pas fait — les règles couvrent les consignes simples (longueur, tableau) ; un commentaire plus subtil n'apprend rien. Le
  français et l'anglais sont reconnus ; une négation compliquée peut être mal lue.
- **Un feedback retiré** : il n'y a pas de route pour retirer un feedback (on le remplace) ; la suppression d'une conversation n'est pas rejouée avant le prochain feedback.
- **La suppression avec le compte** : il n'y a pas de table des utilisateurs (les comptes sont dans Keycloak), donc rien ne l'emporte automatiquement. La personne supprime depuis la page ;
  une purge à la fermeture d'un compte est à brancher avec ce processus.
- **La mémoire dans l'étape `plan`** (langue, vocabulaire métier, collections habituelles) : seule la génération de la réponse la lit pour l'instant.
- **Le tri par pertinence** quand la mémoire dépasse le plafond : on garde ce que la personne a écrit, puis le plus certain, sans regarder la question.
- **La mention dans les conditions d'utilisation** et **le guide d'aide de l'application** (le prompt `app_help`, versionné en base) : à compléter par un administrateur.
- **Un coupe-circuit modifiable depuis l'interface** : `MEMORY_ENABLED` est une variable d'environnement.
- **Une conversation sans mémoire qui n'est pas enregistrée** : « sans mémoire » ne veut dire ni lue ni apprise ; la conversation reste dans l'historique.
