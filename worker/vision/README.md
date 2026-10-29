# worker/vision - description des images et des tableaux (Florence-2 base)

Worker Celery qui **décrit** les images et les tableaux d'une page scannée à partir de leur recadrage. Fait partie de
l'extraction par layout (#403) ; le worker d'extraction (`worker/document_process`) lui envoie les régions retenues et
écrit la description dans le texte de la page (`[Image : ...]`, ou au bout du marqueur d'un tableau) et dans le registre
des régions (`caption`, `caption_model`) - #411.

- Tâche `app.tasks.describe_regions(document_id, page_number, image_key, regions, prompt=None, model=None)` sur la queue
  `document_vision`. `image_key` est l'image de la page en S3 ; `regions` une liste de `{"id", "box", "kind"}` (boîte entre
  0 et 1). Le résultat est un `PageDescriptions` en JSON (`app/contracts.py`) : une description **par id** (une région dont
  le modèle ne dit rien est absente), la version du modèle et la consommation (`usage` : secondes ; les jetons ne sont
  comptés que par les modèles du hub).
- **`model` choisit qui décrit.** Rien, ou `Florence-2-base` : le modèle local (sa seule tâche ; `prompt` ne sert pas). Tout
  autre nom : un modèle du hub qui lit les images (compatible OpenAI), interrogé **par le proxy LLM du backend**
  (`/api/internal/llm/chat`, `app/hub.py`) avec `prompt` (sinon une question pour une image, une pour un tableau, en
  français) et le contexte `usage` donné : le pod ne porte aucune clé du hub, et le backend enregistre la consommation. La
  sortie dit dans `usage` les jetons (comptés par le hub) et les secondes. Il faut donc `BACKEND_API_URL` et
  `WORKER_API_KEY` ; le pod joint le backend (à ouvrir dans la NetworkPolicy du chart si elle est active).
- **Florence-2 répond en anglais.** Le worker d'extraction traduit la description en français avec le modèle de chat du
  pipeline (`CAPTION_TRANSLATE`), et la garde telle quelle si aucun modèle n'est là.
- **Chargé une fois par processus** (environ 2 Go) : la concurrence est de 1, et `TORCH_THREADS` se règle sur les CPU
  donnés au pod. C'est l'étape la plus lente de la chaîne sur CPU. Le coût mesuré est à relever sur la machine cible avant
  de régler les plafonds `CAPTION_*` ; il n'est pas encore mesuré ici (le vrai modèle n'a pas été exécuté).
- `app/contracts.py` est une **copie** de `worker/document_process/app/ocr/contracts.py` : un test échoue si elles divergent.

## Image

Même construction que les autres pods d'OCR : `python:3.12-slim`, `pip` retiré, non root, lecture seule. Le modèle est celui
de Microsoft sur Hugging Face, à une **révision figée** : les poids (`model.safetensors`) et les trois fichiers Python que
`transformers` exécute pour le construire (`trust_remote_code`) sont vérifiés par leur SHA-256 au build. `transformers` est
figé (`==4.49.0`, le code distant est écrit pour cette version), `HF_HUB_OFFLINE=1` et `TRANSFORMERS_OFFLINE=1` : rien n'est
téléchargé à l'exécution. PyTorch vient de l'index CPU.

```bash
docker compose up worker-ocr-vision
```

## Tests

```bash
uv run pytest                                      # le modèle est remplacé par un faux
MODELS_DIR=/chemin/models uv run pytest -m slow    # avec le vrai modèle
```
