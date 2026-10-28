# worker/layout - régions d'une page scannée (PP-DocLayoutV3)

Worker Celery qui prend l'image d'une page scannée et rend ses **régions** - texte, titre, liste, légende, tableau,
image, formule, sigle, tampon, en-tête, pied de page, numéro de page - avec leur boîte (**normalisée entre 0 et 1**
par la taille de la page) et leur **ordre de lecture**. Fait partie de l'extraction par layout (#403) ; le worker
d'extraction (`worker/document_process`) lui envoie les pages et orchestre.

- Tâche `app.tasks.layout_page(document_id, page_number, image_key)` sur la queue `document_layout`. Elle lit l'image
  de la page dans S3 (`ocr-pages/{document}/page-{n}.png`) et rend un `PageLayout` en JSON (`app/contracts.py`). Une
  page sans région est un résultat valide, pas une erreur : l'appelant retombe alors sur l'OCR de liteparse.
- Modèle : l'export **ONNX officiel** de PaddlePaddle (`PaddlePaddle/PP-DocLayoutV3_onnx`, Apache 2.0), lancé par
  ONNX Runtime à travers le pré- et post-traitement de PaddleOCR - PaddlePaddle lui-même n'est pas installé. Il est
  chargé **une fois par processus enfant**.
- `app/layout.py` : les 25 libellés du modèle deviennent les types du contrat (`LABEL_TO_TYPE` ; un libellé inconnu est
  `other`, jamais pris pour du texte) ; le bruit (score, taille), les doublons (une région recouverte à 90 % par une
  meilleure) et l'excès (plafond par page, les pires scores partent) sont écartés ; l'ordre de lecture est celui du
  modèle, renumérotée depuis 0.
- Un **tableau** est gardé dès un score plus bas que les autres régions (`LAYOUT_TABLE_MIN_SCORE`) : voir
  `docs/environment-variables.md`.
- `app/contracts.py` est une **copie** de `worker/document_process/app/ocr/contracts.py` (chaque image est construite
  depuis son dossier) : un test échoue si elles divergent.

## Image

`Dockerfile` : `python:3.12-slim`, `pip` retiré, utilisateur non root, système de fichiers en lecture seule (`HOME=/tmp`).
Le modèle est téléchargé **au build**, à une révision figée et vérifié par son SHA-256 ; le pod ne télécharge rien en
tournant (`PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True`) et marche sans réseau. Chaque processus charge le modèle
(environ 1 Go avec ses bibliothèques) : `-c` du `CMD` est le nombre de pages lues en même temps, à régler sur la
mémoire du pod, avec `ONNX_INTRA_OP_THREADS`.

```bash
docker compose --profile ocr up worker-ocr-layout
```

## Tests

```bash
uv run pytest                 # le modèle est remplacé par un faux
MODELS_DIR=/chemin/models uv run pytest -m slow    # avec le vrai modèle, s'il est dans MODELS_DIR
```
