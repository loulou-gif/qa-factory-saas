---
description: Temps B — exécute les cas validés sur l'application réelle, note le résultat de chaque cas et propose les corrections des cas
argument-hint: <projet> campagne <AAAAMMJJ-HHMMSS>
---
Exécute les cas de tests validés du projet « $ARGUMENTS » sur l'application réelle, en suivant **strictement** la skill `execution-tests`.

- Entrées : `projets/<projet>/03-valide/cas-de-tests.json`, `projets/<projet>/03-valide/jeux-de-donnees.md`, et la fiche de la campagne `projets/<projet>/04-livrables/execution/<campagne>/campagne.json` (lien, comptes de test, actions autorisées, liste des cas).
- Navigateur : uniquement les outils du serveur MCP dont le nom est donné dans la fiche de la campagne (`navigateur`). Les comptes s'utilisent par le nom de leur secret, jamais par leur valeur.
- Sorties : un fichier `resultats/<CT>.json` par cas et les captures dans `captures/`, dans le dossier de la campagne. Ne modifie jamais `03-valide/` : les corrections de cas sont des propositions, écrites dans le résultat du cas.
- Termine par un compte rendu de cinq lignes au plus : cas exécutés, anomalies, cas bloqués et pourquoi.
