---
description: Temps A — analyse le cahier des charges d'un projet et produit cas de tests, ambiguïtés et jeux de données dans 02-a-valider
---
Analyse les documents d'entrée du projet « $ARGUMENTS » en suivant **strictement** la skill `analyse-cdc`, le format `docs/FORMAT-CAS-DE-TESTS.md` et le référentiel `docs/TECHNIQUES-ISTQB.md` (techniques de conception ISTQB uniquement, stratégie des 10 types de tests).

- Entrées : `projets/$ARGUMENTS/01-entrant/` et `projets/$ARGUMENTS/projet.json`.
- Sorties : `projets/$ARGUMENTS/02-a-valider/` → `cas-de-tests.json`, `cas-de-tests.md`, `cas-de-tests.xlsx`, `cas-de-tests.docx` (générés), `ambiguites.md`, `jeux-de-donnees.md`, `matrice-tracabilite.md` (généré).
- Si `02-a-valider/cas-de-tests.json` existe déjà, ne l'écrase pas : demande au responsable du projet s'il veut une nouvelle analyse complète ou une correction (`/corriger`).
- Termine par `python outils/controle.py $ARGUMENTS` à 0 erreur, une ligne de journal, et le compte rendu prévu par la skill.
- Ne déplace jamais les fichiers dans `03-valide`.
