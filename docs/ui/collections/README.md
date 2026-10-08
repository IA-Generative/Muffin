# Collections : liste et fiche détail

Documente la gestion des collections de documents - point d'entrée principal pour organiser les
documents que l'agent de recherche pourra citer. Suit la même logique que
[`docs/ui/admin/`](../admin/README.md) - un sous-dossier par page/fonctionnalité.

Composants Vue : [`frontend/src/components/CollectionsView.vue`](../../../frontend/src/components/CollectionsView.vue)
(liste, recherche, tri), [`frontend/src/components/CollectionDetailView.vue`](../../../frontend/src/components/CollectionDetailView.vue)
(fiche détail : header, description/tags, onglets Paramètres/Documents/Questions-Réponses/Évaluation/Entités
& Relations/Chunks).
Composable : [`useCollections.ts`](../../../frontend/src/composables/useCollections.ts).

## Liste des collections

Recherche par nom/tag, tri (dernière mise à jour, nom, nombre de documents), pagination :

![Liste des collections](screenshots/collections-00-list.png)

## Fiche détail : header (§140)

Le header (nom, badge de visibilité, actions) reste sur une seule ligne. Description et tags sont
regroupés dans un bloc secondaire distinct, repliable via le chevron à côté du badge de visibilité,
ouvert par défaut pour ne rien cacher au premier accès. Les dates de dernière modification
("Modifié par... le...") ne sont plus affichées en permanence : elles apparaissent au survol/focus
de l'icône ⓘ à côté de chaque label ("Description", "Tags").

![Header avec description et tags dépliés](screenshots/collections-02-header-filled.png)

![Header replié - seuls le nom et les onglets restent visibles](screenshots/collections-03-header-collapsed.png)

## Onglets : hiérarchie premier niveau / avancé (§141)

Seuls Paramètres, Documents et Questions/Réponses restent au premier niveau - l'essentiel pour un
usage courant. Évaluation du retrieval, Entités & Relations et Chunks (vues d'analyse/debug) sont
regroupées sous un menu déroulant "Avancé" :

![Onglets premier niveau + menu Avancé](screenshots/collections-tabs-01-primary.png)

![Menu Avancé ouvert](screenshots/collections-tabs-02-advanced-open.png)

Sélectionner un onglet avancé change le libellé du déclencheur ("Avancé" → "Chunks" par exemple)
et le garde surligné comme actif - les URLs par onglet (`/collections/:id/chunks`,
`/collections/:id/relations`, `/collections/:id/evaluation`) restent inchangées, donc les liens
existants continuent de fonctionner :

![Onglet avancé actif, libellé du déclencheur mis à jour](screenshots/collections-tabs-03-chunks-active.png)

Tant que les paramètres de la collection n'ont pas été enregistrés, seul l'onglet Paramètres est
accessible (les autres onglets et le menu Avancé restent désactivés).

## Mode lecture/édition, header collant, transitions (§142)

Le nom, la description et les tags ne sont plus éditables en permanence : un bouton "Modifier"
(icône crayon, à côté du chevron de repli) bascule vers un mode édition explicite, qui redevient
un simple bouton "Terminé" (icône coche) tant qu'il est actif. Tant que la collection n'est pas
prête (nom par défaut, paramètres jamais enregistrés), le mode édition reste forcé ouvert - l'owner
peut nommer sa collection sans clic préalable :

![Mode édition forcé sur une collection fraîchement créée](screenshots/collections-modernize-01-forced-edit.png)

Une fois la collection prête, le mode lecture est celui par défaut au chargement suivant - nom,
description et tags s'affichent en texte statique, sans bouton de suppression de tag ni champ
d'ajout :

![Mode lecture par défaut une fois la collection prête](screenshots/collections-modernize-02b-read-mode.png)

Cliquer sur "Modifier" ré-active les champs éditables :

![Mode édition ré-activé via le bouton Modifier](screenshots/collections-modernize-03-edit-mode.png)

Le nom et la barre d'onglets restent visibles au défilement (`position: sticky`) - le bloc
description/tags, lui, défile normalement et disparaît sous le header une fois qu'on descend dans
le contenu d'un onglet. Le changement d'onglet anime un léger fondu plutôt qu'un remplacement brut
du panneau.

## Documents vivants (§172)

Un **document vivant** est un fichier ODT ou Markdown qui évolue dans le temps : au lieu de le
supprimer puis de le ré-uploader (et de perdre résumé, tags et identité), on le **remplace** par une
nouvelle version, avec un historique de révisions. Réservé au propriétaire de la collection, comme
toute action d'écriture. Composants :
[`CollectionDocumentsTab.vue`](../../../frontend/src/components/CollectionDocumentsTab.vue),
[`LivingDocumentRevisions.vue`](../../../frontend/src/components/LivingDocumentRevisions.vue),
composable [`useLivingDocuments.ts`](../../../frontend/src/composables/useLivingDocuments.ts).

Dans l'onglet Documents, le bouton "Ajouter un document vivant" n'accepte que des fichiers `.odt` ou
`.md` ; un document vivant porte le badge "Document vivant" dans la liste :

![Onglet Documents avec un document vivant](screenshots/living-01-documents-tab.png)

"Créer un document Markdown" permet d'écrire un document de zéro (nom + contenu), sans fichier à
uploader. Le nom reçoit l'extension `.md` si elle manque, nom et contenu ne peuvent pas être vides, et
la première révision est marquée comme écrite dans l'interface :

![Création d'un document Markdown](screenshots/living-04-new-markdown.png)

Sa fiche détail a un onglet **Révisions** supplémentaire : historique (origine, auteur, date), badge
"Courante", bouton "Remplacer par une nouvelle version" (le fichier doit être de même format),
"Télécharger" (la version courante, ou n'importe quelle révision - le fichier est servi par le backend,
jamais par une URL de stockage directe) et "Restaurer" sur une ancienne révision - restaurer ajoute une nouvelle révision, l'historique n'est
jamais réécrit. Chaque écriture ré-indexe ce seul document :

![Historique des révisions](screenshots/living-02-revisions.png)

Pendant qu'une autre personne (ou une autre session du même compte) modifie le document, un
bandeau l'indique avec l'heure d'expiration du verrou, et les actions d'écriture sont désactivées.
Le panneau se rafraîchit toutes les 10 secondes :

![Document verrouillé par quelqu'un d'autre](screenshots/living-03-revisions-locked.png)

Une écriture prend le verrou, envoie la révision affichée (`base_revision`) et son jeton, puis le
relâche ; si le document a été modifié entre-temps ou si le verrou a expiré, l'écriture est refusée
avec un message explicite et l'historique est rechargé.

## Modifier un document vivant avec l'agent (§169)

Dans l'onglet Révisions d'un document vivant, le propriétaire de la collection décrit la modification
voulue ; l'agent prépare une **proposition** qu'on relit avant qu'elle soit enregistrée. Rien n'est écrit
dans la collection avant la validation. Composants :
[`LivingDocumentEdit.vue`](../../../frontend/src/components/LivingDocumentEdit.vue) (la demande et l'état de
la proposition),
[`DraftReviewModal.vue`](../../../frontend/src/components/DraftReviewModal.vue) (la fenêtre d'examen),
composable [`useDocumentDraft.ts`](../../../frontend/src/composables/useDocumentDraft.ts).

![Demande de modification](screenshots/living-edit-01-request.png)

Pendant que l'agent travaille, la fenêtre d'examen s'ouvre avec un indicateur d'attente ; elle se met à jour
toute seule (le panneau interroge le backend toutes les 2 secondes, ce qui garde aussi la proposition en
vie) :

![Modification en préparation](screenshots/living-edit-02-pending.png)

Une fois prête, la fenêtre montre l'**aperçu** du document modifié - un PDF pour un ODT, le texte rendu pour
un Markdown -, la liste de ce qui a changé et les actions : **Valider la modification**, **Refuser**, ou
**Ajuster** (une consigne de plus, appliquée à la proposition). Fermer la fenêtre ne perd rien : la
proposition reste affichée sous forme de carte, avec « Examiner la modification » et « Abandonner » :

![Examen de la modification](screenshots/living-edit-03-review.png)

L'agent ne crée jamais d'image : quand il en juge une utile, il signale l'emplacement dans la rubrique
**Images**. On y dépose un fichier (PNG, JPEG ou GIF, 10 Mo au plus) pour chaque emplacement voulu, puis
« Insérer l'image déposée » : un nouvel aperçu est produit avec l'image dedans. Les images ne sont gérées
que pour les documents ODT :

![Images insérées dans la proposition](screenshots/living-edit-04-images.png)

**Valider** fait de la proposition la révision suivante du document (origine « Modification via le chat »)
et le ré-indexe :

![Révision créée par la validation](screenshots/living-edit-05-validated.png)

Quand la demande n'est pas réalisable (par exemple modifier une liste, ou un paragraphe qui porte une image
ou une note de bas de page), l'agent le dit au lieu de modifier autre chose : il n'y a alors rien à valider,
seulement sa réponse, et on peut ajuster la demande ou refuser. Si l'agent n'arrive pas à produire une
modification applicable, la fenêtre l'indique et propose de reformuler :

![Demande non réalisable](screenshots/living-edit-06-declined.png)

![Échec de la préparation](screenshots/living-edit-07-failed.png)

![Aperçu d'un Markdown](screenshots/living-edit-08-markdown.png)

Tant qu'une proposition existe, elle tient le **verrou** du document : le remplacement par fichier et la
restauration sont désactivés, et le bandeau de verrou le rappelle. Une proposition abandonnée (fiche fermée,
plus aucune consultation) est supprimée avec ses fichiers quand son verrou expire.
