# Routines (#524)

Une **routine** pose une question à l'agent **à intervalles réguliers**, au nom de la personne, sans qu'elle ouvre le chat : « chaque lundi, qu'est-ce qui a
changé dans la collection *Règlements* ? ». Chaque exécution produit une **conversation** qu'on peut ouvrir et poursuivre, et la personne est prévenue par la
cloche (`docs/notifications.md`). Une routine dépense des appels de modèle sans que personne ne soit devant l'écran : la fonction est **activée par défaut**, avec des
limites prudentes (voir plus bas), et un administrateur peut la couper ou les resserrer.

## Ce que fait la personne

Page *Routines* (barre latérale). Une routine a :

| Champ | Détail |
|---|---|
| Nom, question | le texte part à l'agent comme un message du chat (4000 caractères au plus) |
| Portée | des collections (avec ou sans sous-collections), **ou un assistant** ; la recherche sur le web est une option, **désactivée par défaut**. Rien de choisi : tout ce que la personne peut lire, comme dans le chat |
| Rythme | toutes les *n* heures ou jours, tous les jours à une heure, certains jours de la semaine à une heure, une fois par mois — dans **son fuseau horaire** : « 9 h » reste 9 h malgré le changement d'heure ; un 31 tombe le dernier jour des mois plus courts |
| Condition | *toujours*, ou **seulement s'il y a du nouveau** : l'agent n'est pas lancé — donc rien n'est consommé — si aucun document indexé des collections visées n'a été ajouté ou modifié depuis la dernière vérification (demande des collections ou un assistant) |
| Résultat | une nouvelle conversation « Routine : *nom* – *date* » à chaque exécution, ou **une seule conversation** pour toute la routine |
| Notification | à chaque exécution, seulement en cas d'échec, ou jamais |
| État | *active*, *en pause* (par la personne), *suspendue* (par le système ou un administrateur) |

Le formulaire montre les **prochaines dates** du rythme avant qu'on le garde (`POST /api/routines/preview`). *Exécuter maintenant* essaie la routine sans attendre :
la condition « seulement s'il y a du nouveau » ne s'applique pas (on veut voir ce qu'elle fait), les limites oui. L'**historique** donne, par exécution : la date, la
durée, l'état — *réussie*, *échouée*, ou *sautée* avec son motif —, les jetons et le lien vers la conversation.

## Comment elle s'exécute

Un balayage **toutes les minutes**, dans le backend (`RoutineScheduler`, démarré par le `lifespan`), prend les routines échues avec `FOR UPDATE SKIP LOCKED`, avance
leur date dans la **même transaction**, puis démarre un run de l'agent comme le fait `RunService.create_run`. Avec plusieurs réplicas, **une date ne s'exécute
qu'une fois**. Une tâche du processus suit ensuite le run, jusqu'à sa fin ou à la durée permise, et écrit l'historique, compte les échecs et prévient.

- **Pas de rattrapage en rafale** : après une panne, une routine manquée s'exécute **une fois**, sa date suivante est calculée après maintenant.
- **Pas de chevauchement** : si la précédente tourne encore, l'exécution est sautée (`previous_running`) et le dit dans l'historique.
- **Identité hors ligne.** La personne n'est pas là, donc **pas de jeton** : la routine utilise son identifiant, ses **groupes de Muffin relus à chaque
  exécution** et les groupes de son jeton **tels qu'à sa dernière visite** (`user_profiles.groups`, mis à jour à l'ouverture de l'application — même compromis que
  les clés d'API). **Jamais administrateur**, même pour un administrateur. **Aucun outil** (`call_tool` est coupé pour le run) : la routine cherche dans les
  collections et, si c'est autorisé, sur le web ; elle ne peut donc ni écrire, ni appeler un outil qui demande le jeton (#343).
- **Les droits sont ceux du moment.** À chaque exécution, les collections sont filtrées par ce que la personne peut lire : celle qui ne l'est plus est **laissée de
  côté** et la notification le dit (« Pas accessible à vous : *Budget* ») ; s'il n'en reste aucune (ou plus d'assistant utilisable), l'exécution est **sautée**
  (`access_lost`), comptée comme un échec, et la personne en est prévenue.
- **Pas de question posée** : le run n'est pas interactif (`interactive = false`), personne n'est là pour répondre.

## Limites (*Administration → Routines*)

Réglables, et vérifiées **à chaque exécution**, pas seulement à la création :

| Réglage | Défaut |
|---|---|
| Fonction activée | **oui** (un administrateur peut la couper : plus rien ne s'exécute, les routines restent) |
| Routines actives par personne (une routine en pause ne compte pas) | 5 |
| Intervalle minimal entre deux exécutions (comparé à l'écart le plus court du rythme, pas seulement aux « toutes les n heures ») | 60 minutes |
| Exécutions par personne sur 24 heures (`daily_limit` au-delà, à la main aussi) | 10 |
| Exécutions en même temps, pour toute l'application (`busy` au-delà ; le balayage n'en prend pas plus que de places) | 3 |
| Suspension après *n* échecs de suite | 3 |
| Suspension d'un compte **inactif** depuis *n* jours | 60 |
| Durée maximale d'une exécution (au-delà, le run est arrêté et marqué échoué) | 15 minutes |

- **Suspension automatique** : après *n* échecs de suite (un succès remet le compte à zéro) ou quand le propriétaire ne s'est pas connecté depuis *n* jours (la date
  est celle de `user_profiles.last_seen_at`, mise à jour à l'ouverture de l'application et par le relevé de la cloche). La personne est prévenue et **reprend**
  la routine quand elle veut.
- Un **administrateur** voit toutes les routines — propriétaire, rythme, état, dernière exécution, jetons sur 30 jours —, **sans leur question ni leurs
  réponses**, et peut les **suspendre** : seul un administrateur lève cette suspension (elle repasse alors en pause, et le propriétaire la reprend).
- Une exécution qui se perd parce que le pod qui la suivait est tombé est **fermée en échec** par le ménage (toutes les 30 minutes).
- **Consommation à part** : la page *Ma consommation* et la page d'administration montrent les exécutions des routines et leurs jetons (`routines` de
  `/api/usage/me` et `/api/admin/usage`) ; une exécution sautée n'a rien demandé et ne compte pas.

## API

`/api/routines` (propriétaire seulement : celle d'un autre répond `404`) : `GET` (liste), `POST`, `GET/PATCH/DELETE /{id}`, `POST /{id}/pause`, `/resume`, `/run`,
`GET /{id}/runs` (historique paginé), `POST /preview`, `GET /status` (fonction activée, limites, ce que la personne a utilisé). `/api/admin/routines` : `GET`,
`GET/PATCH /settings`, `POST /{id}/suspend`, `/release`. Les refus ont le format de l'API (`detail: { code, message }`) : `fonction_desactivee` (404),
`trop_de_routines` (409), `rythme_invalide`, `intervalle_trop_court`, `collection_inaccessible`, `assistant_inaccessible`, `portee_requise` (422),
`suspendue_par_un_administrateur` (409).

## Sécurité et vie privée

- Une routine agit **au nom de la personne, hors ligne, en lecture seule**, avec ses droits recalculés à chaque exécution ; aucun jeton n'est gardé.
- Une notification ne contient que le nom de la routine, une ligne et un lien — jamais la réponse.
- Le propriétaire est toujours le destinataire : rien ne permet d'envoyer quoi que ce soit à autrui.
- La question d'une routine part, comme un message du chat, vers le modèle ; avec la recherche sur le web, vers un moteur de recherche (désactivée par défaut).

## Pas encore

- Le **courriel** (`docs/notifications.md`).
- Les **garde-fous d'entrée** (#516) : la question n'y passe pas, ni à la création ni à l'exécution, seulement les bornes ci-dessus. Elle devra y passer quand ils
  existeront.
- L'expression **`cron`** en rythme avancé, et la publication sur le flux d'événements (#515).
- Les **outils** (#343) : une routine n'en a aucun, faute de jeton de la personne.
