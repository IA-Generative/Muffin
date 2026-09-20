# Questions de test — database.csv

Fichier : `database.csv` — 19 déclarants, 33 colonnes (données fiscales françaises).

---

## 1. Combien y a-t-il de déclarants dans le fichier ?

**Réponse :** 19

---

## 2. Quel est le revenu fiscal de référence moyen ?

**Réponse :** 15 308,89 (sur 18 déclarants, 1 a un revenu `null`)

---

## 3. Quel est le revenu fiscal de référence le plus élevé ?

**Réponse :** 37 023 — GUILLAUME DIX

---

## 4. Quel est le revenu fiscal de référence le plus bas ?

**Réponse :** 0 — SEBASTIEN TREIZE

---

## 5. Quelle est la répartition par situation de famille ?

**Réponse :**
| Situation | Count |
|-----------|-------|
| M (Marié) | 5 |
| C (Célibataire) | 4 |
| D (Divorcé) | 6 |
| O (Other) | 2 |
| V (Veuf) | 2 |

---

## 6. Quel est le revenu moyen par situation de famille ?

**Réponse :**
| Situation | Revenu moyen | Count |
|-----------|-------------|-------|
| C | 17 611,75 | 4 |
| D | 16 029,83 | 6 |
| M | 13 254,75 | 4 |
| O | 22 284,00 | 2 |
| V | 5 673,50 | 2 |

---

## 7. Combien de déclarants sont nés dans chaque département ?

**Réponse :**
| Département | Count |
|-------------|-------|
| 09 | 2 |
| 25 | 4 |
| 37 | 1 |
| 40 | 1 |
| 46 | 1 |
| 47 | 1 |
| 48 | 2 |
| 51 | 1 |
| 54 | 1 |
| 67 | 2 |
| 75 | 2 |
| 82 | 1 |

---

## 8. Combien de déclarants ont un revenu supérieur à 20 000 ?

**Réponse :** 3

---

## 9. Quels déclarants sont nés en 1962 ?

**Réponse :** 2 déclarants
- STEPHANE DUPONT
- ANGELA DUBOIS

---

## 10. Combien de déclarants sont mariés (situation M) ?

**Réponse :** 5

---

## 11. Quels déclarants ont plus de 3 personnes à charge ?

**Réponse :** 6 déclarants
| Nom | Personnes à charge |
|-----|-------------------|
| RAYMOND SEPT | 4 |
| LUCIEN HUIT | 5 |
| ALIX NEUF | 6 |
| GUILLAUME DIX | 7 |
| REMI ONZE | 8 |
| MARCEL DOUZE | 9 |

---

## 12. Quels sont les 5 déclarants avec les revenus les plus élevés ?

**Réponse :**
| Rang | Nom | Revenu |
|------|-----|--------|
| 1 | GUILLAUME DIX | 37 023 |
| 2 | REMI ONZE | 35 926 |
| 3 | MARCEL DOUZE | 30 509 |
| 4 | BARNARD QUINZE | 17 828 |
| 5 | STEPHANE DUPONT | 17 827 |

---

## 13. Quel est le revenu total cumulé par département de naissance ?

**Réponse :**
| Département | Revenu total | Déclarants |
|-------------|-------------|------------|
| 09 | 0,00 | 1 |
| 25 | 30 200,00 | 4 |
| 37 | 15 253,00 | 1 |
| 40 | 7 365,00 | 1 |
| 46 | 11 347,00 | 1 |
| 47 | 17 827,00 | 1 |
| 48 | 32 828,00 | 2 |
| 51 | 14 059,00 | 1 |
| 54 | 15 396,00 | 1 |
| 67 | 66 435,00 | 2 |
| 75 | 27 827,00 | 2 |
| 82 | 37 023,00 | 1 |

---

## 14. Quel département a le revenu total le plus élevé ?

**Réponse :** 67 (Haut-Rhin) avec 66 435,00 (2 déclarants)

---

## 15. Quelle est la répartition par titre (M/MME) ?

**Réponse :**
| Titre | Count |
|-------|-------|
| M | 12 |
| MME | 7 |

---

## 16. Quel est le nombre maximum de personnes à charge ?

**Réponse :** 9 — MARCEL DOUZE

---

## 17. Quel est le revenu moyen des mariés (M) vs célibataires (C) ?

**Réponse :**
- Mariés (M) : 13 254,75 (4 déclarants avec revenu valide)
- Célibataires (C) : 17 611,75 (4 déclarants)

---

# Questions complexes (multi-étapes)

Ces questions nécessitent des filtres combinés, des calculs dérivés, ou des comparaisons.

---

## 18. Quel est le revenu moyen des déclarants nés dans le département 67 ?

**Réponse :** 33 217,50 (2 déclarants : 15 396 + 51 039)

---

## 19. Quel est le pourcentage de déclarants mariés ?

**Réponse :** ~26,3 % (5 mariés sur 19 déclarants)

---

## 20. Quelle est la différence de revenu moyen entre les mariés et les célibataires ?

**Réponse :** 4 357 (17 611,75 - 13 254,75)

---

## 21. Quel est l'âge moyen des déclarants ?

**Réponse :** ~56 ans (basé sur l'année de naissance 2026 - anneeNaissance)

---

## 22. Quels déclarants ont un revenu inférieur à 10 000 ?

**Réponse :** 2 déclarants
- SEBASTIEN TREIZE (revenu = 0)
- RAYMOND SEPT (revenu = 7 365)

---

## 23. Quel est le revenu médian ?

**Réponse :** 15 253 (valeur médiane sur 18 déclarants avec revenu valide)

---

## 24. Combien de déclarants ont plus de 2 personnes à charge ?

**Réponse :** 10 déclarants

---

## 25. Quel est le revenu total de tous les déclarants ?

**Réponse :** 275 560 (somme de tous les revenus valides)
