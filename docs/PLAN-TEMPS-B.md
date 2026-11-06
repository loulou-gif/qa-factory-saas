# Plan : tests de l'application, mise à jour Squash et automatisation Playwright (temps B dans le SaaS)

Décisions du 2026-11-06 :
- dans Squash, l'application ne met à jour **que les éléments qu'elle a créés** (connus par la correspondance). Si quelqu'un les a modifiés dans Squash entre-temps, elle le signale et ne les écrase pas sans accord ;
- les **comptes de test** de l'application sont saisis par projet et chiffrés. L'agent ne voit jamais les mots de passe ;
- les scripts Playwright sont en **JavaScript ou TypeScript**, au choix du testeur, JavaScript par défaut ;
- la livraison suit l'**ordre du parcours**, lot par lot. Chaque lot est testé avant de passer au suivant.

## Parcours visé

1. Les cas sont validés et le lien de l'application est renseigné. **Tester l'application** : l'agent exécute chaque cas de haut niveau dans un vrai navigateur. Il note pour chaque cas « réussi », « échoué », « bloqué » ou « non exécuté », avec la preuve. Il propose aussi des corrections des cas d'après ce qu'il a observé : libellés réels, étapes manquantes.
2. **Résultats** : une page courte (chiffres clés, couverture des exigences, anomalies). Le rapport se télécharge en HTML et en Excel. **Modifications proposées** : chaque cas modifié est montré avant/après, le testeur coche ce qu'il garde et valide.
3. **Mettre à jour Squash** : évaluation de ce qui existe (créer, mettre à jour, inchangé, modifié dans Squash par quelqu'un d'autre), puis confirmation et mise à jour, sans doublon.
4. **Automatiser** : l'application propose les scénarios à automatiser en priorité (criticité, fréquence d'usage, stabilité observée, coût). Le testeur coche, choisit JS ou TS et lance la génération.
5. **Exécuter les scripts** depuis l'application. Ensuite : résultats, rapport Playwright, et archive des scripts à télécharger.

## Architecture retenue

- **Un navigateur par tâche.** L'application ajoute, pour la durée de la tâche, un serveur MCP Playwright au moteur (`POST /mcp` de l'API OpenCode, vérifié sur OpenCode 1.19.5). Il est lancé :
  - en mode headless et isolé ;
  - limité au domaine de l'application testée (`--allowed-origins`) ;
  - avec les comptes de test en **secrets** (`--secrets`). L'agent saisit le *nom* du secret (`COMPTE_1_MOT_DE_PASSE`), le MCP saisit la valeur, et la valeur est masquée dans tout ce que l'agent reçoit (vérifié dans @playwright/mcp 0.0.84).
- Le message envoyé à l'agent n'active que les outils de ce navigateur-là (champ `tools` de `/session/{id}/message`). Une tâche ne voit pas le navigateur d'une autre.
- L'agent écrit des fichiers simples et contrôlés : un JSON par cas exécuté, plus les captures. Le rapport, les statistiques et l'application des modifications sont faits **sans IA**, par `outils/execution.py`. Ils sont donc testables et reproductibles.
- Garde réseau : le lien de l'application passe le même contrôle que Squash (réseau interne refusé sur le service public).
- Risque résiduel connu : tant que le conteneur moteur a un accès Internet (voir `SPEC-MODELES.md`, isolement du moteur), un document piégé pourrait pousser l'agent à faire sortir des données par Python. Les comptes saisis doivent rester des comptes de recette.

## Lots

| Lot | Contenu | État |
|---|---|---|
| 1 | Application testée (lien, comptes chiffrés, actions autorisées) ; tâche « tester » ; résultats, rapport HTML/Excel ; modifications proposées et validation | fait (tests : `saas/tests/test_tests_application.py` ; essai réel sur Linux/Docker à faire) |
| 2 | Mise à jour Squash des éléments créés par QA Factory : évaluation, détection des changements faits dans Squash, mise à jour sans doublon (fork MCP : option `mettreAJour` de `publierFichier`, outil `update_published_test_cases`) | fait : nouvelle version `CT0001.N` et ancienne en Obsolète (rien n'est réécrit ni supprimé), dossier « QA Factory - <projet> » au premier envoi (tests : `saas/tests/test_mise_a_jour_squash.py`, `squash-tm-mcp/test/miseAJour.test.ts` ; chaîne vérifiée sur le vrai Squash, projet SauceDemo, le 2026-11-06) |
| 3 | Proposition de priorités d'automatisation ; génération Playwright JS/TS dans un dépôt d'automatisation par projet (`templates/automatisation/`) | à faire |
| 4 | Exécution des scripts depuis l'application, résultats, rapport Playwright, archive des scripts | à faire |

## À vérifier sur un vrai déploiement (Linux / Docker)

- Image : installer Chromium pour Playwright dans l'image (aujourd'hui désactivé) et `@playwright/mcp` en version figée.
- `tools` avec motif (`nav_12_*`) bien appliqué par OpenCode à un serveur MCP ajouté à la volée.
- Captures : le chemin passé à `browser_take_screenshot` est résolu par rapport au dossier de travail du MCP (`cwd` = dossier de la campagne).
