# Notifications (#524)

Un endroit où l'application dit à la personne qu'il se passe quelque chose, sans qu'elle ait à ouvrir la bonne page. **Dans l'application seulement** : le
courriel n'est pas proposé (voir « Pas encore »).

## Ce que voit la personne

- Une **cloche** dans la barre latérale (*Notifications*) avec le nombre de non lues. Le compteur est relevé **à l'ouverture de l'application, puis toutes les heures**
  tant qu'elle reste ouverte (et au retour sur un onglet resté longtemps en arrière-plan) ; ouvrir le panneau recharge la liste et le compteur. Un lecteur d'écran
  l'entend (`aria-live`). Replié, la barre ne montre que la pastille.
- Un panneau : titre, une ligne, date, lien. Cliquer ouvre le lien (un chemin de l'application) et marque la notification lue ; *Tout marquer comme lu* ; une
  croix supprime ; *Voir les plus anciennes* charge la suite (par curseur). Échap ferme.
- Des **préférences** dans *Paramètres* : une case par type, « dans l'application », cochée par défaut. Un type décoché n'est plus enregistré du tout.

## Les types

| Type | Quand | Qui est prévenu |
|---|---|---|
| `routine.completed` / `routine.failed` / `routine.suspended` | résultat d'une routine, selon son réglage ; mise de côté (`docs/routines.md`) | le propriétaire |
| `document.failed` | un document n'a pas pu être traité (une seule fois : un échec qui se répète ne sonne pas deux fois) | celui qui l'a ajouté, à défaut le propriétaire de la collection |
| `import.completed` | un import ZIP est fini, réussi ou non | celui qui l'a lancé |
| `share.received` | une collection est partagée avec un **groupe fait dans Muffin** | les membres du groupe, sauf celui qui partage |
| `feedback.status` | le statut d'un signalement change (#148) | celui qui l'a fait |

Un partage **par adresse** ne prévient personne : il est fait à l'aveugle (`docs/collection-sharing.md`), Muffin ne connaît pas le destinataire avant qu'il se
connecte.

## Ce qu'une notification contient

Un titre, une ligne, un lien et des identifiants (`data`) : **ce que la personne peut déjà lire dans l'application**. Jamais le texte d'une réponse, jamais l'erreur
d'un traitement (elle peut contenir ce que le pipeline a vu du fichier), jamais les noms de fichiers d'un import. Le lien est **toujours un chemin de
l'application** : `https://…` et `//…` sont écartés à l'enregistrement.

## API

`/api/notifications`, propriétaire seulement (une notification d'un autre répond comme si elle n'existait pas) :

| Route | Rôle |
|---|---|
| `GET /api/notifications?limit=&cursor=&unread_only=` | liste, la plus récente d'abord ; `next_cursor` pour la suite, `unread` pour le compteur |
| `GET /api/notifications/unread-count` | le nombre de non lues (et la date de dernière connexion, voir plus bas) |
| `POST /api/notifications/read` | `{ "ids": [...] }`, ou `{}` pour toutes |
| `DELETE /api/notifications/{id}` | supprime |
| `GET` / `PUT /api/notifications/preferences` | les préférences, par type |

Le code appelle `notify(...)` (`services/notification_service.py`) : dans **sa propre session**, sans jamais faire échouer ce qui l'appelle (une cloche qui ne
sonne pas ne doit pas casser un import).

## Durée de vie

**90 jours**, lues ou non (`RETENTION_DAYS`), purgées par le balayage des routines (toutes les 30 minutes). Et **500 par personne** au plus : les plus anciennes
partent d'abord, pour qu'une routine toutes les heures ne remplisse pas la table.

## Pas encore

- Le **courriel** (configuration SMTP, courrier sans contenu, désabonnement, regroupement).
- La publication sur le flux d'événements (#515 : `notification.created`) et le flux en direct (#510) à la place du relevé horaire.
- Les notifications d'autres événements.
