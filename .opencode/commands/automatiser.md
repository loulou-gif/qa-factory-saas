---
description: Temps B — écrit les scripts Playwright (JavaScript ou TypeScript) des scénarios choisis, en relevant les vrais libellés et locators dans l'application
---
Génère les scripts Playwright du projet « $ARGUMENTS » en suivant **strictement** la skill `automatisation-playwright`.

- Entrées : la fiche de la génération `projets/<projet>/04-livrables/automatisation/<generation>/generation.json` (scénarios choisis, langage, dépôt, lien, comptes de test, actions autorisées, navigateur), `projets/<projet>/03-valide/cas-de-tests.json`, `jeux-de-donnees.md`, et dans le dépôt `agents/AGENTS.md` et `agents/features/`.
- Navigateur : uniquement les outils du serveur MCP nommé dans la fiche (`navigateur`), pour observer l'application. Les comptes s'utilisent par le nom de leur secret, jamais par leur valeur.
- Sorties : Page Objects, tests et données **dans le dépôt** indiqué par la fiche, et un fichier `resultats/<CT>.json` par scénario dans le dossier de la génération. Ne modifie jamais `03-valide/` ni les specs de `04-livrables/specs/`.
- N'exécute pas les scripts : l'exécution se lance depuis l'application.
- Termine par un compte rendu de cinq lignes au plus : scripts écrits, scénarios non générés et pourquoi.
