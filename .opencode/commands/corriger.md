---
description: Reporte les modifications faites dans l'Excel ou le Word des cas de tests et/ou applique une correction demandée, puis régénère tous les fichiers
---
Correction : « $ARGUMENTS » (le premier mot est le projet ; le reste, s'il existe, est la demande du responsable du projet).

Suis la section « Corrections » de la skill `analyse-cdc` :
1. Travaille uniquement dans `projets/<projet>/02-a-valider/`. Si les fichiers ne sont que dans `03-valide/`, explique qu'il faut d'abord les remettre dans `02-a-valider/` (c'est le responsable du projet qui déplace) et arrête-toi.
2. Importe d'abord les modifications manuelles : `python outils/synchroniser_vues.py <projet>`. En cas de conflit (code 2), demande quel fichier fait foi et relance avec `--source`. Ne choisis jamais à sa place.
3. S'il y a une demande écrite : applique-la au JSON (et à `ambiguites.md` / `jeux-de-donnees.md` si besoin), sans renuméroter, en incrémentant `meta.version`, puis relance `python outils/synchroniser_vues.py <projet>` pour régénérer le Markdown, l'Excel et le Word.
4. `python outils/controle.py <projet>` jusqu'à 0 erreur.
5. Journal, puis compte rendu : modifications importées depuis l'Excel ou le Word, corrections appliquées (ids concernés), nouveaux avertissements éventuels.
