# Images jointes à un message (#512)

On peut **joindre une ou plusieurs images** à un message du chat — capture d'écran d'une erreur, schéma, document photographié — et poser sa question :
« pourquoi cette erreur ? », « que dit ce tableau ? ». La réponse en tient compte, avec ou sans recherche documentaire, et l'image reste dans la conversation.

## Ce que voit la personne

Un bouton *Joindre une image* dans le composeur (ou le **collage** d'une capture, ou le **glisser-déposer**) : une vignette apparaît tout de suite, l'envoi au serveur
se fait derrière, la vignette se retire d'un clic. Le message part quand toutes les images sont gardées ; avec des images et rien d'écrit, la question est
« Que montre cette image ? ». Dans le fil, l'image est une vignette au-dessus du texte du message, qu'un clic agrandit ; elle revient après un rechargement.

- **Quand il n'y a aucun modèle capable de lire les images**, le bouton est désactivé et dit pourquoi (« Aucun modèle capable de lire les images n'est disponible »),
  et le serveur refuse l'envoi (`409`, `pas_de_modele_vision`) : une image n'est jamais envoyée à un modèle qui l'ignorerait.
- La page **réduit** une image trop grande avant de l'envoyer (2048 pixels de côté au plus, en PNG, puis en JPEG si elle pèse encore trop) : la lire coûte des
  jetons, pas de la finesse. Un SVG, un GIF ou un PDF n'est pas une image jointe.
- Le **trombone** reste celui des **fichiers** (collection temporaire de la conversation, ZIP) : une image choisie par le trombone y est un document, comme avant.
  Déposée sur le composeur, une image est jointe au message quand un modèle la lit, et un autre fichier est joint comme avec le trombone.

## Comment le modèle la lit, avec le moins d'appels

Le graphe ne change pas, et il n'y a **aucun appel de plus**.

- **Le planificateur ne voit pas l'image** : son appel reçoit seulement « l'utilisateur a joint N image(s) à ce message », et la consigne de ne **jamais répondre seul**
  ni demander ce que montre l'image. Un plan qui répondrait (`direct`) ou poserait des questions (`clarify`) sans l'avoir vue est transformé en recherche sans
  requête, qui mène à la réponse. Une question sur l'image seule ne cherche rien dans les collections ; une question qui demande aussi des documents garde ses requêtes.
- **Seul le modèle qui écrit la réponse la reçoit** (appel n°2). Une réponse à une image **n'a pas besoin d'extrait** : sans elle, la réponse « je n'ai rien trouvé dans vos
  bases » n'est pas donnée, et ce que montre l'image n'a pas à être cité. La vérification des affirmations après coup n'est pas lancée : ce que dit le modèle d'une image
  n'est pas dans les extraits qu'elle lirait.
- **Le modèle** : celui qui est choisi s'il lit les images ; sinon le **premier du hub qui les lit** (`GET /api/internal/llm/vision-models`, mis en cache comme la liste des
  modèles de chat). Ce changement n'est **jamais silencieux** : le run l'écrit (`answer_model_switched`, avec le modèle) et le chat l'affiche parmi les étapes
  (« Réponse écrite par un modèle qui lit les images ») et dans le détail d'exécution.
- **Une relance sur la même image** (« et la deuxième colonne ? ») : sans nouvelle image, les images du **message utilisateur précédent** sont lues de nouveau. Au-delà,
  l'historique ne garde que « [L'utilisateur avait joint 1 image(s)] ».
- Sans modèle de vision, ou si les images ont disparu, la réponse le dit clairement et **aucun appel de modèle n'est perdu**.

## Ce que le serveur garde, et comment

- **Choisie avant d'être envoyée** : `POST /api/images/attachments` (multipart) garde l'image sans conversation ni message — il n'y en a peut-être pas encore —
  sous `images/attached/{id}`, à son propriétaire. `GET` la montre à lui seul dans le composeur, `DELETE` la retire. `GET /api/images/attachments/status` dit si les images sont
  proposées.
- **Vérifiée sur ses octets, pas sur sa parole** (`app/core/image_bytes.py`) : PNG, JPEG ou WebP lus dans l'en-tête, **jamais de SVG ni de HTML**, même nommé `.png` ; un côté d'au
  plus `IMAGES_MAX_SIDE`, un poids d'au plus `IMAGES_ATTACH_MAX_BYTES` (5 Mo). La lecture s'arrête un octet après la limite : un envoi énorme n'est pas lu en entier.
- **Bornes** : `IMAGES_PER_MESSAGE` images par message (4), `IMAGES_STAGED_MAX` en attente par personne (12). Ce qui a été choisi et **jamais envoyé** est effacé (ligne et
  fichier) au plus tard `IMAGES_STAGED_TTL_HOURS` (24 h) après, la prochaine fois que la personne en choisit une.
- **Envoyée avec un message** : `RunCreate.image_ids`. Avant d'écrire quoi que ce soit, le serveur vérifie qu'elles sont **à la personne**, **pas encore envoyées**, en nombre
  permis et qu'un modèle les lit ; sinon `422` (`image_introuvable`, `trop_d_images`) ou `409`, sans conversation ni message créés. Elles deviennent alors celles du message
  de la personne et de sa conversation : une image **déjà envoyée ne se réutilise pas** dans un autre message, et celle d'un autre n'est jamais acceptée.
- **Lue par son propriétaire seulement** (`GET /api/conversations/{id}/images/{image}`, `nosniff`, le type vérifié à l'entrée) ; supprimée **avec la conversation**, fichier compris. Elle
  est dans `MessageOut.images` du message qui la porte, avec `origin: "attached"` et sans étiquette « générée par IA ».
- **Le worker** la reçoit par `GET /api/internal/runs/{run}/images/{image}` (clé de service) : seulement une image **jointe** de la conversation du run et de la personne du run.

## Vie privée

- L'image part au **hub de modèles**, comme le texte du message. Quand le hub est externe à l'organisation, c'est à l'administrateur de choisir des modèles acceptables.
- Elle n'est **ni indexée**, ni dans une collection, ni dans la journalisation, ni dans les traces d'exécution (qui ne gardent que du texte) : seul le texte de la
  consigne part dans l'appel du planificateur.

## Pas encore

- Que le modèle **voie** l'image qu'il a fait générer (seules les images jointes par la personne sont lues).
- Le **redimensionnement côté serveur** : il se fait dans la page, le serveur ne fait que refuser ce qui dépasse ses bornes.
- Les **images dans le serveur MCP** (l'outil `search` reste textuel).
