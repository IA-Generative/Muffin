# worker/ocr - texte des régions d'une page scannée (PP-OCRv5 mobile)

Worker Celery qui lit le texte des **régions de texte** (texte, titre, liste, légende) d'une page scannée, régions que
`worker/layout` a trouvées, et rend des **lignes et des mots positionnés** dans le repère de la page (boîtes
**normalisées entre 0 et 1**) - de quoi alimenter `text_boxes` et le surlignage des passages cités (#350). Fait partie de
l'extraction par layout (#403).

- Tâche `app.tasks.ocr_regions(document_id, page_number, image_key, regions)` sur la queue `document_ocr`. `regions` est
  la liste `regions` du `PageLayout` ; le résultat est un `PageText` en JSON (`app/contracts.py`).
- Modèles : les exports **ONNX officiels** de PaddlePaddle - détecteur `PP-OCRv5_mobile_det_onnx` et reconnaisseur des
  écritures latines `latin_PP-OCRv5_mobile_rec_onnx` (Apache 2.0) - lancés par ONNX Runtime à travers le pré- et
  post-traitement de PaddleOCR. PaddlePaddle lui-même n'est pas installé. Chargés **une fois par processus enfant**.
- **Chaque région est lue depuis son propre recadrage.** Dedans, les régions qui ne sont pas du texte (tableau, image,
  formule, sigle, tampon, en-tête, pied de page, numéro) sont **peintes en blanc** : ce qui les entoure ne se mélange pas
  au texte. Une formule *dans* une ligne (`other`) n'est pas peinte, elle couperait la phrase. Le recadrage reçoit une
  marge puis une **bordure blanche** (`OCR_CROP_BORDER_PIXELS`) : sans elle, le détecteur coupe un titre en morceaux.
- **Les mots** : PaddleOCR donne des morceaux de caractères (`activit` puis `é `, une apostrophe seule), pas des mots.
  `build_words` coupe la ligne à ses blancs et prend, pour chaque mot, l'union des morceaux qui le recouvrent ; une ligne
  dont les morceaux ne refont pas le texte est coupée au prorata des caractères.
- Les lignes gardent leur score (`OCR_LINE_MIN_SCORE=0` les garde toutes) : juger d'une lecture médiocre revient à
  l'appelant. Les lignes ne sont pas réordonnées entre colonnes à l'intérieur d'une région.
- `app/contracts.py` est une **copie** de `worker/document_process/app/ocr/contracts.py` : un test échoue si elles
  divergent.

## Image

Même construction que `worker/layout` : `python:3.12-slim`, non root, lecture seule, les deux modèles téléchargés au
build à des révisions figées et vérifiés par leur SHA-256, aucun accès réseau à l'exécution.

```bash
docker compose --profile ocr up worker-ocr
```

## Tests

```bash
uv run pytest                 # les modèles sont remplacés par un faux
MODELS_DIR=/chemin/models uv run pytest -m slow    # avec les vrais modèles
```
