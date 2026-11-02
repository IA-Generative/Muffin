# Licences du pod TTS

Ce pod assemble des œuvres sous des licences **différentes**. La plus contraignante est celle des poids du modèle, et
elle n'est pas une licence libre au sens de l'OSI : lisez-la avant tout déploiement.

| Composant | Licence | Où |
|---|---|---|
| **Poids Kitten-TTS 2** (`lm/`, `decoders/`, `voices/`, `config.json`) - Stellon Labs / KittenML | **Stellon Labs Community License** (voir ci-dessous) | `KittenML/kitten-tts-2`, révision `c93cb7c271baa51d9ae8204d5277988906f235a2` ; texte complet dans l'image : `/models/kitten-tts-2/LICENSE.md` |
| Encodeur de locuteur (`speaker/`) | MIT (© CNRS) | `/models/kitten-tts-2/speaker/LICENSE` |
| Codec audio `s3gen_meanflow.safetensors` (Resemble AI) | MIT | `ResembleAI/chatterbox-turbo`, révision `749d1c1a46eb10492095d68fbcf55691ccf137cd` (la fiche du dépôt déclare MIT ; le dépôt ne contient pas de fichier de licence) |
| Paquet Python `kittenml` | Apache-2.0 | PyPI, `kittenml==0.9.7` |
| PyTorch, FastAPI, uvicorn, soundfile (libsndfile), librosa, etc. | BSD / MIT / Apache-2.0 / LGPL (libsndfile) selon le paquet | `uv.lock` donne la liste exacte des versions |

## Stellon Labs Community License (poids Kitten-TTS 2) - ce qu'il faut retenir

Résumé non contractuel de la version du 5 juillet 2024 ; **le texte fait foi** (`LICENSE.md` du dépôt du modèle, aussi dans
l'image).

- **Recherche, usage non commercial** : libre et gratuit.
- **Usage commercial** (y compris « pour les opérations internes de votre organisation » et la mise à disposition d'un
  service ou d'une API) : gratuit **tant que** vous et vos affiliés générez **moins de 1 000 000 USD de revenu annuel** et
  avez reçu **moins de 1 000 000 USD de financement cumulé** (capitaux, dette, subventions...). Il faut en outre **vous
  déclarer auprès de Stellon Labs**. Au-delà d'un de ces seuils, **la licence prend fin** et il faut en demander une autre,
  accordée à la seule discrétion de Stellon Labs.
- **Distribution et attribution** (section IV(a)) : si vous distribuez les poids, un dérivé, ou un produit ou service qui
  les utilise, vous devez (i) fournir une copie de la licence, (ii) garder la mention du fichier `NOTICE` ci-joint, (iii)
  afficher **« Powered by KittenML »** sur un site, une interface, une page « à propos » ou la documentation du produit.
- **Restrictions** (section IV(b)) : respect des lois (dont le contrôle des exportations) et de la politique d'usage
  acceptable de Stellon Labs ; interdiction d'utiliser le modèle **ou ses sorties** pour créer ou améliorer un modèle
  d'IA générative de fondation, ou pour entraîner / distiller un autre modèle (hors « fine tune » et LoRA du modèle).
- Droit applicable : États-Unis, Californie. Aucune garantie.

**Ce que cela implique pour Muffin** : le pod est **désactivé par défaut** et ne doit être activé qu'après vérification, par
les responsables de la structure qui déploie, que ces conditions sont tenues (seuils, déclaration, mention « Powered by
KittenML » dans l'interface qui propose la voix). Cette note n'est pas un avis juridique. Les images publiées par ce dépôt
**contiennent les poids** : les distribuer est une « distribution » au sens de la section IV(a).
