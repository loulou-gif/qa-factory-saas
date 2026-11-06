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
| 3 | Proposition de priorités d'automatisation ; génération Playwright JS/TS dans un dépôt d'automatisation par projet (`templates/automatisation/`) | fait : `outils/automatisation.py` (priorités sans IA : criticité, importance, parcours nominal, stabilité aux derniers tests, nombre d'étapes ; dépôt `projets/<projet>/05-automatisation/`, langage fixé à la création ; contrôle des scripts, retrait des secrets, inventaire), tâche « automatiser » avec le navigateur de la tâche, skill `automatisation-playwright`, page « Automatiser les tests » (tests : `saas/tests/test_automatisation.py` ; écriture par un vrai modèle sur Linux/Docker à faire). Les scripts ne sont pas exécutés : lot 4 |
| 4 | Exécution des scripts depuis l'application, résultats, rapport Playwright, archive des scripts | fait : `outils/execution_scripts.py`, sans IA. Avant chaque exécution : fichiers du gabarit rétablis, `.env` supprimé, scripts contrôlés (imports limités à `@playwright/test` et au dépôt ; ni `process`, ni réseau hors navigateur, ni code dynamique, ni adresse hors de l'application ; ni `node_modules` ni configuration ajoutés). Navigateur limité aux domaines de l'application (`--host-resolver-rules`, variable `QAF_HOTES_AUTORISES` lue par `playwright.config`), environnement vide sauf URL et comptes, traces désactivées, secrets retirés de tous les rapports (le rapport HTML de Playwright écrit les valeurs saisies). Vérification `tsc` pour TypeScript (avertissements). Résultats par scénario (réussi, échoué, instable, ignoré, non exécuté), rapport Playwright servi par l'application, inventaire mis à jour, archive .zip du dépôt. Playwright 1.64.1 dans l'image (`/opt/qaf-playwright`). Tests : `saas/tests/test_execution_scripts.py`, dont un essai réel sur SauceDemo à la demande |
| 5 | Documents de recette, paramètres de l'outil, menu latéral | fait : cahier de tests sans IA, au modèle Excel de l'entreprise s'il est déposé (`outils/cahier_modele.py` : en-têtes reconnus par synonymes, une ligne par étape ou par cas, marqueurs `{{…}}`), sinon au modèle interne ; manuel utilisateur rédigé par l'assistant (tâche « manuel », commande `rediger-manuel`, skill `redaction-manuel`) sous forme de données (`contenu.json` + captures), contrôlé puis mis en page par l'application dans le modèle Word de l'entreprise (`outils/manuel_modele.py` : styles du modèle, `{{CONTENU}}`, `{{SOMMAIRE}}`, marqueurs) ou le modèle interne ; Paramètres › Modèles d'IA (modèle principal, modèle par usage, clés OpenRouter / Anthropic / OpenAI chiffrées, essai avant enregistrement) et relais `/ia` (le moteur ne reçoit plus aucune clé) ; Paramètres › Modèles de documents ; menu latéral sans sous-menu (Nouvelle analyse, Projets, Activité ; Paramètres en bas, au-dessus de l'utilisateur). Tests : `saas/tests/test_documents.py` |
| 6 | Modèles gratuits et relais automatique | fait : fournisseurs Google Gemini, Groq, Cerebras, Mistral, DeepSeek ajoutés au relais (fournisseurs natifs d'OpenCode, adresses fixes) ; liste déroulante des modèles connus (`CATALOGUE` de `app/parametres.py`) ; chaîne de secours (le moteur change de modèle dans la même session quand la limite est atteinte : 401/402/403/429, quota, crédit, clé absente, fournisseur muet) ; autorisation explicite des modèles gratuits partagés ; clés personnelles par utilisateur, retrouvées par le relais via l'en-tête `x-opencode-session-id` (session de la tâche ou session mère d'un sous-agent). Tests : `saas/tests/test_modeles_ia.py`, `test_moteur.py` |

## Vérifié sous Docker (2026-11-06, Docker Desktop, image `qa-factory-saas:local`)

- Image : Playwright 1.64.1 (`/opt/qaf-playwright`, exécution des scripts, `tsc`) et `@playwright/mcp` 0.0.84 (`/opt/qaf-playwright-mcp`, navigateur de l'agent) dans deux dossiers séparés, chacun avec son Chromium ; dépendances système installées. Les deux ne partagent pas la même version de Playwright : dans un seul dossier, le Chromium des scripts manquait.
- Navigateur de l'agent : démarre sous l'utilisateur `qaf`, se connecte à SauceDemo avec les noms des secrets sans jamais renvoyer la valeur, refuse un autre domaine.
- Exécution des scripts dans le conteneur web : 3 sur 3 réussis sur SauceDemo, aucun secret dans les fichiers produits ; gabarit TypeScript sans erreur `tsc`.
- Parcours complet avec les deux conteneurs et le faux modèle : écriture des scripts par OpenCode, exécution, progression, rapport Playwright, archive.
- Corrigé : construit depuis un poste Windows, `saas/demarrer.sh` en fins de ligne CRLF empêchait les conteneurs de démarrer (`.gitattributes` et normalisation dans le Dockerfile).

## Reste à vérifier avec un vrai modèle (clé OpenRouter)

- `tools` avec motif (`nav12_*`) bien appliqué par OpenCode à un serveur MCP ajouté à la volée.
- Captures : le chemin passé à `browser_take_screenshot` est résolu par rapport au dossier de travail du MCP (`cwd` = dossier de la campagne).
- Manuel utilisateur (lot 5) : captures écrites dans `captures/` par le MCP, qualité de la rédaction, ouverture du .docx dans Word (sommaire mis à jour à l'ouverture).
- Qualité des cas exécutés (lot 1) et des scripts écrits (lot 3) : locators relevés, titres `[CT…]` exacts, scripts acceptés par le contrôle du lot 4.
