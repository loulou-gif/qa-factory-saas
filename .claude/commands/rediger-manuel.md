---
description: Temps B, application web — rédige le contenu du manuel utilisateur en parcourant l'application, avec captures, au format JSON mis en page par QA Factory
argument-hint: <projet> redaction <AAAAMMJJ-HHMMSS>
---
Rédige le manuel utilisateur du projet « $ARGUMENTS » en suivant **strictement** la skill `redaction-manuel`.

- Entrées : la fiche `projets/<projet>/04-livrables/manuel/redactions/<redaction>/redaction.json` (fonctionnalités et cas validés, lien, comptes de test par le nom de leur secret, actions autorisées, navigateur), `projets/<projet>/03-valide/cas-de-tests.json` et `jeux-de-donnees.md`.
- Navigateur : uniquement les outils du serveur MCP nommé dans la fiche (`navigateur`). Les comptes s'utilisent par le nom de leur secret, jamais par leur valeur.
- Sorties : les captures PNG dans `<redaction>/captures/` et le contenu dans `<redaction>/contenu.json`, rien d'autre. Ne modifie jamais `03-valide/`. N'écris ni Word ni code : l'application met le contenu en page dans le modèle Word.
- Termine par un compte rendu de cinq lignes au plus : chapitres écrits, captures, points à confirmer.
