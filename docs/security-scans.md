# Analyses de sécurité de la CI

La CI lance deux familles d'analyses [Trivy](https://trivy.dev), toutes deux définies dans [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## Ce qui est rapporté et ce qui bloque

| Job | Cible | Rapporte | Bloque la CI |
|---|---|---|---|
| `scan-trivy-conf` | Dockerfiles, charts Helm, workflows | toutes les sévérités, dans l'onglet *Security* | non |
| `scan-trivy-images` | les images construites | toutes les sévérités avec correctif, dans l'onglet *Security* | non |
| `gate-trivy-conf` | idem | — | **oui** : une mauvaise configuration critique ou haute |
| `gate-trivy-images` | idem | — | **oui** : une vulnérabilité **critique avec correctif disponible** |

- Les vulnérabilités **sans correctif** (`ignore-unfixed`) ne bloquent jamais, et ne sont d'ailleurs pas rapportées pour les images : il n'y a rien à faire tant qu'aucun correctif n'existe.
- Le filtre de sévérité réduit aussi le rapport envoyé à l'onglet *Security*. C'est pourquoi les jobs `gate-*` sont séparés des jobs `scan-*` : les premiers décident du blocage, les seconds gardent la vue complète.
- Les deux jobs `gate-*` figurent dans `all-jobs-passed`, donc une PR ne peut pas être fusionnée s'ils échouent.

## Corriger une alerte

C'est la première réponse, et la plus courante :

- **Image de base** : reconstruire sur une base à jour (`python:3.12-slim`, `nginx-unprivileged`). Les Dockerfiles du frontend font aussi un `apk upgrade`. Dependabot propose chaque semaine la mise à jour des bases et des dépendances (voir [`.github/dependabot.yml`](../.github/dependabot.yml)).
- **Dépendance Python** : `uv lock --upgrade-package <nom>` dans `backend/` ou `worker/<service>/`.
- **Dépendance npm** : mettre à jour `frontend/` et son `pnpm-lock.yaml`.

## Accepter une alerte

Seulement quand elle ne peut pas être corrigée (aucun correctif ni contournement) ou qu'elle ne s'applique pas à notre usage. Ajouter une entrée dans [`.trivyignore.yaml`](../.trivyignore.yaml), à la racine, avec :

- l'**identifiant** de l'alerte ;
- une **raison** (`statement`) : pourquoi on l'accepte ;
- une **date de réexamen** (`expired_at`) : passé cette date, l'exception cesse de s'appliquer et l'alerte revient dans la CI.

```yaml
vulnerabilities:
  - id: CVE-2026-00000
    # Cible : image `worker-document-process` uniquement (paths limite la portée).
    paths:
      - "usr/local/lib/python3.12/site-packages/exemple-1.0.dist-info/METADATA"
    statement: >-
      Aucun correctif publié ; la fonction vulnérable n'est jamais appelée (le worker ne lit pas de
      fichier fourni par un tiers).
    expired_at: 2027-01-31

misconfigurations:
  - id: DS-0000
    statement: Faux positif : <raison>.
    expired_at: 2027-01-31
```

Une exception sans raison ni date n'est pas acceptable en revue : elle masque une alerte sans que personne ne la réexamine.
