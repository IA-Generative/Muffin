# worker/table - tableaux d'une page scannée (SLANet_plus)

Worker Celery qui lit les **tableaux** d'une page scannée - leur structure (lignes, colonnes, cellules fusionnées) et le
texte de chaque cellule - parmi les régions que `worker/layout` a trouvées. Fait partie de l'extraction par layout
(#403) ; le worker d'extraction (`worker/document_process`) lui envoie les tableaux et en tire le marqueur du texte de la
page et le contenu gardé en base (#410).

- Tâche `app.tasks.table_regions(document_id, page_number, image_key, regions)` sur la queue `document_table`. `regions`
  est la liste `regions` du `PageLayout` ; seules celles de type `table` sont lues. Le résultat est un `PageTables` en
  JSON (`app/contracts.py`) : pour chaque tableau, ses cellules (ligne, colonne, étendue, texte, boîte entre 0 et 1 sur la
  page), la présence d'un en-tête et un score.
- Modèles : les exports **ONNX officiels** de PaddlePaddle - `SLANet_plus_onnx` pour la structure, et les modèles de
  texte du pod `ocr` (détecteur mobile, reconnaisseur latin) pour les cellules. Lancés par ONNX Runtime à travers le
  pré- et post-traitement de PaddleOCR ; PaddlePaddle lui-même n'est pas installé. Chargés **une fois par processus
  enfant**.
- **Comment une cellule reçoit son texte** (`app/tables.py`) : SLANet_plus rend la structure en jetons HTML (`<tr>`,
  `<td rowspan=..>`) et une boîte par cellule, dans l'ordre des `<td>` ; l'OCR lit les lignes de texte du recadrage ;
  chaque ligne va à la cellule qui en contient le plus. Une ligne qui en couvre plusieurs - le détecteur a joint ce que
  l'espacement des colonnes laissait proche - est coupée aux cellules avec les morceaux de caractères du
  reconnaisseur. Si le modèle ne rend pas autant de boîtes que de cellules, aucun texte ne peut être donné à sa cellule :
  la tâche échoue et la page est lue autrement.
- **Le score ne vient pas du modèle seul.** Le score de structure de SLANet_plus vaut 1,00 sur un tableau sans bordures
  qu'il lit faux (une cellule fusionnée inventée, un en-tête étalé sur deux lignes : 0,98). Le score d'un tableau est donc
  celui du modèle, **abaissé** par les lignes de texte qui ne sont dans aucune cellule, par une ligne sans rien dedans et
  par une cellule fusionnée vide - ce qui ramène ce tableau à 0,49 quand les deux bien lus restent à 1,0 et 0,999. Au
  worker d'extraction de décider ce qu'un tableau douteux vaut (`reliable`).
- **L'en-tête** : la première ligne en est un quand il y a quelque chose dessous, que chacune de ses cellules dit quelque
  chose et que la plupart ne sont pas des nombres.
- `app/contracts.py` est une **copie** de `worker/document_process/app/ocr/contracts.py` : un test échoue si elles divergent.

## Limite connue

SLANet_plus lit mal certains tableaux **sans bordures**. `SLANeXt_wired` (aussi officiel en ONNX) tombe juste sur celui
de mes essais, mais coûte une vingtaine de fois plus (1,8 s contre 0,1 s) ; relire un tableau douteux avec lui est une
piste, pas encore faite.

## Image

Même construction que les autres pods d'OCR : `python:3.12-slim`, `pip` retiré, non root, lecture seule, les trois modèles
téléchargés au build à des révisions figées et vérifiés par leur SHA-256, aucun accès réseau à l'exécution. Environ
0,5 Go par processus : `-c` du `CMD` est le nombre de pages lues en même temps.

```bash
docker compose up worker-ocr-table
```

## Tests

```bash
uv run pytest                 # les modèles sont remplacés par un faux
MODELS_DIR=/chemin/models uv run pytest -m slow    # avec les vrais modèles
```
