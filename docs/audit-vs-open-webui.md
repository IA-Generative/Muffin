# Audit : Muffin face à Open WebUI

Objectif : avoir **à peu près les mêmes fonctions qu'Open WebUI, et davantage là où cela compte**. Cet audit dit où Muffin en est, où il est
déjà devant, ce qui lui manque, et dans quel ordre le combler.

## En bref

1. **Ce ne sont pas le même produit.** Open WebUI est une plateforme de chat IA généraliste (541 routes dans la version 0.12.5 : modèles,
   outils, voix, images, notes, canaux, calendriers, automatisations, code…). Muffin est une plateforme de **connaissance documentaire
   gouvernée** avec un agent de recherche. Prétendre faire « tout, en mieux » condamne à courir derrière une cadence de livraison qu'on
   ne tiendra pas.
2. **Là où Muffin est déjà devant, et c'est son terrain :** le RAG. Citations au passage exact avec page et zones encadrées, contrôle
   d'ancrage des réponses, collections hiérarchiques à droits hérités, résumés / questions-réponses / entités générés à l'ingestion,
   SQL sur les fichiers tabulaires, documents modifiables avec validation, reconstruction d'index sans interruption, qualité et impact
   environnemental mesurés. Open WebUI n'a pas l'équivalent de la plupart de ces points.
3. **Là où Muffin est en retard, et cela se voit tout de suite à l'usage :** le confort du chat (recherche et dossiers de conversations,
   partage et export, entrée d'images, réponse en vrai flux), l'**extensibilité** (pas d'outils définis par l'utilisateur, pas de client
   MCP), les **connecteurs de sources** (SharePoint, OneDrive, Drive) et l'**ouverture par API** (aucun point d'entrée compatible OpenAI).
4. **Ce qu'il ne faut probablement pas copier :** canaux d'équipe, calendriers, automatisations, notes, génération d'images, interpréteur de
   code libre. Open WebUI les fait ; les refaire dans Muffin coûte cher et ne sert pas son cœur. Mieux vaut **coopérer** : Muffin a déjà un
   outil Open WebUI, une synchronisation des collections et un serveur MCP.
5. **Le levier le plus fort est une API compatible OpenAI** : Muffin devient consommable par Open WebUI, par un IDE, par n'importe quel
   client, sans qu'on reconstruise leurs interfaces.

## Méthode et limites

- **Open WebUI** : l'instance de test du dépôt (`ghcr.io/open-webui/open-webui:v0.12.5`). J'ai lu son schéma OpenAPI public (541 routes,
  groupées par domaine) et ses formulaires de configuration (RAG, recherche web, voix, images…). Ce schéma m'a permis de **vérifier** la
  présence du partage, des dossiers, de l'épinglage, de l'archivage et de la recherche de conversations, des clés d'API, de LDAP, de la
  mémoire, du reclassement, des connexions de connaissance externes et du chargeur YouTube. Il n'a **aucune route SCIM**. **Je n'ai pas utilisé l'application** : ce que je
  dis de son comportement vient de ce schéma et de ma connaissance des versions précédentes, pas d'un essai.
- **Muffin** : le code de la branche `dev` (écrans, routes, docs). J'ai aussi essayé l'interface à l'aide d'une API simulée pour les derniers
  écrans, mais **pas d'un déploiement réel**.
- **Aucune mesure de qualité** n'est faite ici : je ne dis pas que les réponses de Muffin sont meilleures ou moins bonnes que celles
  d'Open WebUI. La dernière section propose comment le mesurer.
- Les points marqués *(à vérifier)* sont ceux dont je ne suis pas sûr.

Légende : **➕** Muffin devant · **🟰** équivalent · **🔻** Muffin en retard · **❌** absent de Muffin.

## 1. Chat et expérience

| Fonction | Open WebUI 0.12.5 | Muffin | |
|---|---|---|---|
| Réponse en flux | websocket / SSE, mot à mot | texte partiel et étapes interrogés toutes les 700 ms | 🔻 |
| Étapes de la recherche visibles | traces dans l'analytique | étapes en direct dans le chat, panneau de détail | ➕ |
| Choix du modèle | modèles personnalisés (« model builder ») avec prompt système, connaissances et outils attachés | sélecteur de modèle du hub | 🔻 |
| Pièces jointes | fichiers, images (vision), pages web, Drive / OneDrive | fichiers (collection temporaire de la conversation) ; **images jointes au message, lues par un modèle de vision** (`docs/image-attachments.md`) | 🔻 |
| Voix | STT / TTS à moteurs, appel vocal temps réel | dictée et lecture vocale (`useVoiceInput`, `useVoiceOutput`) | 🔻 |
| Génération d'images | plusieurs moteurs | optionnelle, désactivée par défaut : adresse compatible OpenAI (`docs/image-generation.md`) | 🟰 |
| Interpréteur de code, terminaux | oui | non ; à la place, SQL + graphiques sur les fichiers tabulaires | ❌ |
| Mémoire de l'utilisateur | oui | non | ❌ |
| Notes | oui | non (les documents modifiables jouent un rôle voisin) | ❌ |
| Dossiers, étiquettes, épingles, archives | oui | renommer et supprimer seulement | 🔻 |
| Recherche dans les conversations | oui | non trouvée | 🔻 |
| Partage d'une conversation, export | oui | non trouvé *(à vérifier)* | 🔻 |
| Arbre de messages (branches), édition d'un message | oui | « Rejouer » une réponse | 🔻 |
| Bibliothèque de prompts de l'utilisateur, commandes | oui (versionnés) | prompts **système** administrables et versionnés seulement | 🔻 |
| Compétences (*skills*) réutilisables | oui (nouveau en 0.12) | non | ❌ |
| Questions de précision à choix | non trouvé dans le schéma *(à vérifier)* | oui, avec options, bornées | ➕ |
| Thème sombre | oui | oui | 🟰 |
| Langues | nombreuses | français seulement (pas de bibliothèque d'i18n) | 🔻 |
| Application installable (PWA) | oui (manifeste) | non | 🔻 |
| Canaux d'équipe, calendriers | oui | non | ❌ |
| Garde-fous sur la saisie | filtres (fonctions) à écrire soi-même | **garde-fous** administrables (règles, modèle, service HTTP), mode surveillance ou blocage, masquage, audit (`docs/guardrails.md`) | ✅ |
| Automatisations | oui (généralistes) | **routines** : une question posée à l'agent à intervalles réguliers, pour surveiller sa base documentaire (`docs/routines.md`), et centre de notifications (`docs/notifications.md`) | 🟰 |

## 2. RAG et connaissances (le cœur)

| Fonction | Open WebUI | Muffin | |
|---|---|---|---|
| Recherche hybride dense + BM25 | oui, poids réglable | oui, fusion RRF (`docs/search.md`) | 🟰 |
| **Reclassement** (*reranker*) | interne ou externe, `TOP_K_RERANKER` | **absent** | 🔻 |
| Mode « contexte complet » | oui | non (réponses étagées : questions déjà répondues, résumés, passages) | 🔻 |
| Moteurs d'extraction | Tika, Docling, Datalab Marker, Azure Document Intelligence, Mistral OCR, MinerU, PaddleOCR-VL, chargeur externe | liteparse + pipeline propre (OCR, mise en page, tableaux, légendes d'images) | 🟰 (moins interchangeable, plus intégré) |
| Découpage | récursif, par jetons, par en-têtes Markdown | plusieurs stratégies, dont par modèle, **par collection** | ➕ |
| Résumés, questions-réponses, entités, relations, étiquettes générés par document | non | oui | ➕ |
| **Collections hiérarchiques**, droits hérités, routage entre collections | bases plates | oui, avec routage et exploration des sous-collections | ➕ |
| Citations | extraits et lien vers le fichier | **passage exact, page, zones encadrées**, citations vérifiées par identifiant ; fichier téléchargeable et ouvert à la page | ➕ |
| Contrôle d'ancrage des affirmations | non | oui, après la réponse | ➕ |
| Fichiers tabulaires (SQL, graphiques) | via l'interpréteur de code | outil dédié, SQL isolé, graphiques | ➕ |
| Modifier / créer un document avec validation | non (les « notes » sont libres) | oui : proposition à relire, valider, ajuster, refuser | ➕ |
| Reconstruction d'index sans arrêt, changement de modèle d'embedding par collection | réindexation globale | reconstruction bleu/vert, retour arrière | ➕ |
| Documents web rafraîchis automatiquement | non trouvé ; les « automatisations » de la 0.12 pourraient le permettre *(à vérifier)* | oui (adresse web, relecture planifiée) | ➕ |
| Import ZIP en arborescence, suggestion de rangement, doublons | non | oui | ➕ |
| **Sources externes** (Drive, OneDrive, connexions de connaissance externe) | oui | **absentes** (dépôt, adresse web, ZIP) | 🔻 |
| Recherche web | une vingtaine de moteurs, plusieurs chargeurs de pages | SearXNG, à l'initiative de l'utilisateur | 🔻 (suffisant ?) |
| Vidéo YouTube | chargeur dédié | non | ❌ |
| Mesurer la qualité du retrieval | évaluations de modèles (arène) | évaluation par collection (paires QA), score de discussion, tableau de qualité | ➕ |

## 3. Agent, outils, extensibilité

| Fonction | Open WebUI | Muffin | |
|---|---|---|---|
| Outils définis par l'utilisateur ou l'administrateur | Python, serveurs OpenAPI, serveurs d'outils | **non** : outils internes fixes (recherche, listes, tabulaire, web, heure) | 🔻 |
| Plugins (filtres, actions, *pipes*), pipelines | oui | non | ❌ |
| MCP | via les serveurs d'outils | **serveur** MCP (recherche) ; **pas de client** MCP | 🔻 |
| Sous-agents, automatisations | oui | non | ❌ |
| Orchestration de la recherche | modèle + outils | plan en un appel, recherche en code, réponse en un appel (2 appels au lieu de 4 à 5) | ➕ |
| Outils au nom de l'utilisateur | secrets par serveur | jeton de l'utilisateur disponible pour un run (mis en place), **aucun outil ne s'en sert encore** | 🟰 (prêt) |

## 4. Utilisateurs, sécurité, administration

| Fonction | Open WebUI | Muffin | |
|---|---|---|---|
| Authentification | OIDC, LDAP, en-tête de confiance, clés d'API personnelles, double authentification | OIDC Keycloak (la double authentification et l'annuaire se règlent côté Keycloak) ; jeton porteur pour l'API ; **pas** de clé d'API personnelle | 🔻 |
| Groupes et droits | groupes, accès lecture / écriture par ressource | groupes, partages lecture / écriture, collection publique, invitation par adresse | 🟰 |
| Interface d'administration | très large | réglages, prompts versionnés, CGU, signalements, usage, synchronisation Open WebUI | 🟰 |
| Analytique d'usage | modèles, utilisateurs, jetons, sessions, traces | usage par utilisateur, **eau et énergie estimées**, tâches, métriques d'exécution | ➕ |
| Qualité des réponses suivie | retours des utilisateurs | retours + raisons, taux d'ancrage, tableau de qualité | ➕ |
| Accessibilité, conformité (DSFR, CGU) | non | oui | ➕ |
| Exploitation à l'échelle | possible, plus simple (un conteneur) | Postgres, Qdrant, Redis, workers, KEDA, chart Helm par composant ; **plus lourd à exploiter** | 🔻 / ➕ selon le besoin |
| API ouverte | `/api/chat/completions`, `/openai/*`, `/responses` compatibles OpenAI | API REST propre à l'application + MCP ; **pas de point d'entrée compatible OpenAI** | 🔻 |

## 5. Où Muffin est déjà vraiment devant

1. **Citations et preuves** : passage exact, page, zones, vérification des identifiants, contrôle d'ancrage, fichier ouvert à la page.
2. **Connaissance structurée** : hiérarchie de collections, droits hérités, résumés, questions-réponses, entités et relations.
3. **Données tabulaires** : SQL isolé et graphiques, au lieu d'un interpréteur de code généraliste.
4. **Documents vivants** : modifier ou créer un document depuis le chat, avec relecture et validation.
5. **Exploitation du RAG** : reconstruction d'index sans arrêt, rangement suggéré, doublons, rafraîchissement des pages web.
6. **Mesure** : qualité (ancrage, retours), évaluation du retrieval, impact environnemental.
7. **Cadre public** : accessibilité DSFR, CGU, Keycloak, souveraineté du modèle via le hub.

## 6. Les écarts, par priorité

Effort : **S** quelques jours · **M** une à deux semaines · **L** plusieurs semaines.

### P0 : ce que l'utilisateur remarque en premier

| # | Chantier | Effort | Pourquoi |
|---|---|---|---|
| 1 | **Recherche dans les conversations**, épinglage, dossiers | M | Au bout de quelques semaines, on ne retrouve plus rien. Absent aujourd'hui. |
| 2 | **Partage et export** d'une conversation | S–M | Une réponse sourcée est faite pour être transmise. |
| 3 | **Flux de réponse en direct** (SSE) à la place du sondage de 700 ms | M | Ressenti de rapidité ; supprime aussi les requêtes de sondage. |
| 4 | **Reclassement** (*reranker*) en option par collection | M | Plus forte hausse de pertinence attendue en RAG ; se mesure avec l'évaluation existante. |
| 5 | **Entrée d'images** dans le chat (modèle multimodal du hub) | M | Capture d'écran, schéma, document photographié. |

### P1 : ce qui change la portée de Muffin

| # | Chantier | Effort | Pourquoi |
|---|---|---|---|
| 6 | **API compatible OpenAI** (`/v1/chat/completions`, `/v1/models`, une collection ou un assistant = un « modèle ») | M | Muffin devient utilisable depuis Open WebUI, un IDE, n'importe quel client. Meilleur rapport effet / coût. |
| 7 | **Outils définis par l'administrateur** : client MCP et serveurs OpenAPI, avec **le jeton de l'utilisateur** et validation | L | L'extensibilité manque le plus ; la plomberie du jeton est déjà posée. |
| 8 | **Connecteurs de sources** : SharePoint / OneDrive, Drive, Nextcloud, avec synchronisation | L | Les documents vivent ailleurs ; sans connecteur, il faut les déposer à la main. |
| 9 | **Assistants** : une collection + des consignes + des outils, partagés comme un « modèle » | M | Équivalent du « model builder » d'Open WebUI, appuyé sur ce que Muffin sait déjà faire. |
| 10 | **Prompts de l'utilisateur** et commandes (`/`) | S–M | Réutiliser une consigne. |

### P2 : à faire si le besoin se confirme

Mémoire de l'utilisateur · génération d'images (si le hub la propose) · clés d'API personnelles · internationalisation · application
installable (PWA) · mode « contexte complet » pour les petites collections · chargeur YouTube · plus de moteurs de recherche web · branches de messages.

### À ne pas faire (ou à laisser à Open WebUI)

Canaux d'équipe, calendriers, automatisations, notes libres, interpréteur de code généraliste. Open WebUI les couvre ; la synchronisation
des collections et l'outil Muffin pour Open WebUI permettent de **garder les deux** sans dupliquer.

## 7. Stratégie proposée

1. **Gagner sur le RAG gouverné** : c'est là que Muffin est devant et là que l'écart se creuse (reclassement, assistants, connecteurs).
2. **Combler le confort du chat** (P0) : sans cela, un utilisateur qui compare ne retient que ce qui manque.
3. **Ouvrir Muffin** (API OpenAI, client MCP, outils au nom de l'utilisateur) plutôt que tout reconstruire.
4. **Coopérer avec Open WebUI** pour ce qui n'est pas le cœur (canaux, notes, automatisations), via la synchronisation et l'outil existants.

## 8. Comment prouver que c'est « mieux »

Les écarts ci-dessus sont des fonctions. Pour dire « meilleur », il faut des chiffres sur les **mêmes questions** :

- un jeu de 50 à 100 questions réelles sur un même corpus, chargé dans Open WebUI et dans Muffin ;
- **rappel des sources** (la bonne page est-elle retrouvée ?), **taux d'ancrage** (les affirmations sont-elles soutenues ?), **latence**, **nombre d'appels
  au modèle**, **coût** ; l'évaluation par collection, les paires QA et le tableau de qualité de Muffin en fournissent déjà une partie ;
- une relecture à l'aveugle par des utilisateurs sur un échantillon.

Je n'ai fait aucune de ces mesures : c'est la suite logique de cet audit, avant de promettre « mieux » à qui que ce soit.
