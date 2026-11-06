---
name: generation-tests-playwright
description: Temps B — génère les Page Objects et tests Playwright JavaScript à partir des specs CONFIRMÉES, dans le dépôt d'automatisation du projet, les exécute et tient l'inventaire de couverture. À utiliser pour /generer-tests, /recette et pour initialiser un dépôt d'automatisation.
---

# Génération des tests Playwright (temps B)

Le code ne vit pas dans `qa-factory` mais dans le dépôt d'automatisation du projet (`projet.json` → `automatisation.depot`), organisé comme les projets ANSUT et Orange eFacture.

## Initialiser le dépôt (première fois)

Si `automatisation.depot` est vide ou n'existe pas, demander au responsable du projet où le créer (habituellement `C:\Users\HP\Desktop\SYNELIA\<PROJET>_AUTOMATION`), puis copier `templates/automatisation/` :

- `agents/AGENTS.md` : remplacer les marqueurs `{{APPLICATION}}`, `{{URL}}`, `{{ESPACES}}`, `{{ACTIONS_AUTORISEES}}` par les valeurs de `projet.json`, `{{LANGAGE}}` par `JavaScript` et `{{EXT}}` par `js` ; ne rien ajouter d'inventé ;
- `.env.example` et `config/env.js` : un couple `COMPTE_<n>_IDENTIFIANT` / `COMPTE_<n>_MOT_DE_PASSE` par compte (`APP_USERNAME` / `APP_PASSWORD` restent acceptés pour le compte 1) ;
- `agents/project-overview.md` : à remplir depuis le CDC (faits) et `ambiguites.md` (points à confirmer) ;
- `package.json`, `playwright.config.js`, `config/env.js`, `.env.example`, `.gitignore`, `utils/evidence.js`, `utils/evidence-reporter.js`, `utils/unique.js` (le dossier `ts/` du modèle sert à la variante TypeScript de l'application web, ne pas le copier ici) ;
- copier les specs CONFIRMÉES dans `agents/features/`.

Puis `npm install`, `npx playwright install chromium`, et reporter le chemin dans `projet.json`.

## Générer les tests d'une fonctionnalité

Respecter `agents/AGENTS.md` du dépôt. En résumé :

1. Seules les specs au statut **CONFIRMÉE** (ou les scénarios confirmés d'une spec PARTIELLE) sont automatisées. Une spec BROUILLON : lancer d'abord `/explorer`.
2. Réutiliser les Page Objects existants ; ne créer que ce qui manque ; aucune assertion dans les Page Objects.
3. Un test par scénario, titre `[CT0001] <titre du scénario> @<fonctionnalite>`, un `test.step` par STEP (texte = WHEN/THEN de la spec), données dans `data/<fonctionnalite>.json`, suffixe unique pour les créations.
4. Exécuter : `npx playwright test --grep @<fonctionnalite>`. En cas d'échec : distinguer défaut du test (corriger, 3 tentatives max) et défaut applicatif (ne pas contourner, le classer FAIL avec la preuve).
5. Mettre à jour `docs/test-inventory.md` du dépôt (modèle : `templates/exemples/exemple-inventaire-olib.md`) : ID, scénario de spec, test, statut PASS / FAIL / BLOCKED / NEEDS_DISCOVERY / NOT_RUN, preuve, commentaire.
6. Reporter dans le JSON validé le lien vers le test (`"automatisation": {"test": "<spec>::<titre>"}`) **en passant par `02-a-valider`** si le responsable du projet le souhaite pour le cahier ; sinon, la traçabilité reste dans l'inventaire.
7. Optionnel, si le responsable du projet le demande : `mark_test_case_automated` dans Squash pour les cas PASS (outil MCP).

## Interdits

- Fixtures personnalisées, TypeScript, Cucumber, `waitForTimeout` sans nécessité démontrée.
- Affaiblir une assertion ou désactiver un test pour obtenir du vert.
- Exécuter un scénario destructif hors `application.actions_autorisees`.
