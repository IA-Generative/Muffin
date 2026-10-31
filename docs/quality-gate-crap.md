# Le contrôle de qualité CRAP des projets Python

La CI note chaque fonction Python avec son **score CRAP** (*Change Risk Anti-Patterns*) et échoue quand l'une dépasse le plafond de
son projet.

```
CRAP = complexité² × (1 − couverture)³ + complexité
```

- **Complexité** : la complexité cyclomatique de la fonction (le nombre de chemins : `if`, `for`, `while`, `except`, `and`/`or`…).
- **Couverture** : la part de ses branches que les tests exécutent.

Une fonction simple n'est jamais « crap », même sans test (jusqu'à une complexité de 5, elle ne dépasse pas 30). Une fonction
complexe n'est acceptable que couverte. Et une fonction dont la complexité seule dépasse le seuil ne passe jamais, même couverte à
100 % : il faut la découper.

| Score | Lecture |
|---|---|
| < 5 | excellent |
| 5 à 15 | acceptable |
| 15 à 30 | à surveiller : ajouter des tests ou simplifier |
| > 30 | risqué à modifier : à tester ou à découper en priorité |

## Où et comment

- L'action [`.github/actions/crap-gate`](../.github/actions/crap-gate/action.yml) est appelée par chaque job de
  [`unit-tests.yml`](../.github/workflows/unit-tests.yml), juste après les tests. Elle lit le rapport LCOV (`--cov-branch`) et utilise
  [`crap4py`](https://pypi.org/project/crap4py/) (version épinglée) ; son rapport est dans le résumé du job.
- Les tests de chaque projet écrivent `lcov.info` (couverture de **branches**, pas seulement de lignes).

## Les plafonds

Un seuil de 30 sur tout le code ferait échouer la CI tout de suite : certains projets ont déjà des fonctions au-dessus. Le plafond de
chaque projet est donc **30**, ou **son pire score du jour** quand il a déjà de la dette : rien de pire n'y entre, et on le baisse au fil
du nettoyage.

| Projet | Plafond | Fonctions au-dessus de 30 | Pire fonction |
|---|---:|---:|---|
| `worker/layout`, `worker/ocr`, `worker/table`, `worker/vision`, `worker/owui_sync` | 30 | 0 | – |
| `worker/document_edit` | 35 | 1 | `_Editor._body_paragraph_style` (34) |
| `worker/tabular` | 50 | 1 | `_draw_lines` (49) |
| `worker/evaluation` | 90 | 3 | `_start_task` (90) |
| `worker/document_process` | 110 | 6 | `update_collection_tags` (110) |
| `backend` | 760 | 64 (dont 14 au-dessus de 100) | `_run_tabular_query` (756) |

**Le plafond ne se relève jamais.** Quand on découpe ou qu'on teste les pires fonctions, on baisse le plafond du projet dans
`unit-tests.yml` (`max-crap`) pour garder le gain. Le plafond du backend est celui qui protège le moins : une nouvelle fonction à 400
passerait encore. C'est le premier à baisser.

## En local

```bash
cd backend            # ou worker/<nom>
uv run --with pytest-cov pytest --cov=app --cov-branch --cov-report=lcov:lcov.info
uvx crap4py@0.1.1 app/ --lcov lcov.info              # le rapport, du pire au meilleur
uvx crap4py@0.1.1 app/ --lcov lcov.info --max-crap 30   # le contrôle, avec un code de sortie
```

## Quand le contrôle échoue

Le message dit quel projet dépasse son plafond, et le résumé du job liste les fonctions les plus risquées. Deux sorties, dans l'ordre :

1. **Découper** : une fonction à forte complexité fait plusieurs choses ; chacune devient une fonction que l'on teste seule.
2. **Couvrir** : des tests qui passent par les branches (`if`/`else`, `except`) de la fonction. Le score tombe vite : une fonction de
   complexité 10 passe de 110 à 10 quand tous ses chemins sont exécutés.

Ne relevez pas le plafond pour faire passer un changement.

## Limites

- Les fonctions **sans donnée de couverture** (fichier jamais importé par les tests) ne font pas échouer le contrôle : `crap4py`
  les marque `N/A`. Un fichier que les tests n'importent pas échappe donc au score.
- Le contrôle porte sur **tout** le code d'un projet, pas seulement sur ce qu'un changement touche : il n'empêche pas d'ajouter une
  fonction à 40 dans un projet dont le plafond est à 110. Seuls les projets à 30 le font.
- La couverture mesurée est celle des tests unitaires de la CI ; les tests qui nécessitent un service absent de la CI ne comptent pas.
