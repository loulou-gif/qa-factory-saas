# QA Factory

Chaîne de production des livrables de test, pilotée par un agent (Claude Code ou OpenCode) et des serveurs MCP :

**cahier des charges → cas de tests + questions + jeux de données → validation → Squash TM + specs d'automatisation → (lien de la plateforme disponible) → exploration → en parallèle : tests Playwright, cahier de tests, manuel utilisateur.**

Tout passe par un seul fichier validé, `cas-de-tests.json` : Squash, le cahier Excel et les specs en sont générés avec les mêmes identifiants (`EX-001`, `CT0001`). Rien n'est réécrit à la main à côté.

Les cas de tests sont conçus **uniquement avec les techniques reconnues par l'ISTQB** (partitions d'équivalence, valeurs limites, tables de décision, transitions d'états, cas d'utilisation, critères d'acceptation, estimation d'erreurs…), chacun avec sa technique et son type de test. L'analyse indique aussi **quels types de tests effectuer** : fonctionnel, performance, sécurité, utilisabilité, compatibilité, fiabilité, maintenabilité, portabilité, confirmation et régression, chacun retenu, à confirmer ou non retenu avec sa justification. Référentiel : `docs/TECHNIQUES-ISTQB.md`.

**Pour savoir à quoi sert chaque document et comment l'utiliser : `docs/GUIDE-UTILISATION.md`.**

## Installation (une fois par poste)

QA Factory fonctionne avec **Claude Code** ou **OpenCode** (même dépôt, mêmes règles, mêmes skills, mêmes commandes). Guide détaillé pour OpenCode : `docs/OPENCODE.md`.

1. Programmes : Claude Code ou OpenCode, Node.js 20+, Python 3 avec `openpyxl` et `python-docx` (`pip install openpyxl python-docx`), Pandoc.
2. Le MCP Squash : cloner `squash-tm-mcp`, puis `npm install` et `npm run build`.
3. Un jeton d'API Squash personnel (Squash → Mon compte → Jetons d'API).
4. Trois variables d'environnement, lues à la fois par `.mcp.json` (Claude Code) et `opencode.json` (OpenCode) :
   ```powershell
   setx SQUASH_MCP_INDEX "C:\chemin\vers\squash-tm-mcp\dist\index.js"
   setx SQUASH_TM_BASE_URL "https://squash.smile.ci/squash/api/rest/latest"
   setx SQUASH_TM_API_TOKEN "<jeton>"
   ```
   Aucun jeton n'est écrit dans le dépôt.
   Si Squash refuse de créer le jeton avec le message « Aucun secret JWT n'est défini pour cette instance », l'administrateur Squash n'a pas activé les jetons d'API. En attendant, utiliser son identifiant et son mot de passe Squash à la place du jeton (le MCP passe alors en authentification Basic) :
   ```powershell
   setx SQUASH_TM_USERNAME "<identifiant Squash>"
   setx SQUASH_TM_PASSWORD "<mot de passe Squash>"
   ```
   Ces valeurs restent dans les variables d'environnement du poste, jamais dans le dépôt. Si les deux modes sont définis, le jeton est prioritaire.
5. `python outils/verifier_installation.py` → « Poste prêt ».
6. Ouvrir l'agent dans ce dossier (`claude` ou `opencode`) et vérifier que `squash-tm` et `playwright` sont connectés.

## Utilisation

| Étape | Qui | Commande (Claude Code ou OpenCode) | Résultat |
|---|---|---|---|
| 1. Créer le projet | Responsable | `/nouveau-projet saucedemo https://www.saucedemo.com 28` | `projets/saucedemo/` et `projet.json` |
| 2. Déposer les documents | Responsable | (explorateur de fichiers) | CDC, US, DSF dans `01-entrant/` |
| 3. Analyser | Agent | `/analyser saucedemo` | `02-a-valider/` : cas (techniques ISTQB), stratégie de types de tests, questions, jeux de données |
| 4. Relire, corriger | Responsable + agent | modifier l'Excel ou le Word, puis `/corriger saucedemo` ; ou `/corriger saucedemo <demande>` | nouvelle version dans `02-a-valider/`, tous les fichiers à jour |
| 5. **Valider** | **Responsable** | **déplacer **tout le contenu** de `02-a-valider/` dans `03-valide/`** | validation |
| 6. Publier dans Squash | Agent, accord du responsable du projet | `/publier saucedemo` | exigences + cas liés dans Squash |
| 7. Specs d'automatisation | Agent | `/specs saucedemo` | specs BROUILLON dans `04-livrables/specs/` |
| 8. Explorer la plateforme | Agent | `/explorer saucedemo` | découvertes, écarts, specs CONFIRMÉES |
| 9. Recette, en parallèle | Agent | `/recette saucedemo` | tests Playwright exécutés + cahier Excel + manuel Word, produits ensemble |
| (ou séparément) | Agent | `/generer-tests`, `/cahier`, `/manuel` | un seul de ces livrables |
| Suivi | — | `/statut` | avancement de chaque projet |

Les étapes 1 à 7 forment le **temps A** (réception du cahier des charges, sans besoin de l'application). Les étapes 8 et 9 forment le **temps B** : elles ne démarrent qu'avec le lien de la plateforme, l'environnement et les comptes de test. **Le cahier de tests et le manuel ne sont produits qu'en temps B**, en parallèle de l'écriture des scripts automatisés. Les détails : `CLAUDE.md`.

Les cas de tests existent en quatre formats : `cas-de-tests.json` (la source), `cas-de-tests.md` (relecture), et **`cas-de-tests.xlsx` / `cas-de-tests.docx`, modifiables directement** par un testeur qui préfère Excel ou Word. Après une modification, `/corriger <projet>` repère le fichier modifié, reporte les changements dans le JSON et met à jour les autres. Détails : `docs/GUIDE-UTILISATION.md`.

## Ce que contient le dépôt

```text
qa-factory/
├── AGENTS.md                 règles et workflow communs (lu par OpenCode, importé par CLAUDE.md)
├── CLAUDE.md                 entrée Claude Code (importe AGENTS.md)
├── README.md                 ce guide
├── .mcp.json                 serveurs MCP pour Claude Code (variables d'environnement)
├── opencode.json             serveurs MCP, outils désactivés et permissions pour OpenCode
├── .claude/
│   ├── settings.json         permissions Claude Code
│   ├── commands/             source des commandes (/analyser, /publier, /specs, /explorer, /recette…)
│   └── skills/               les 7 skills, partagées par Claude Code et OpenCode
├── .opencode/
│   ├── commands/             commandes OpenCode, générées depuis .claude/commands
│   └── agents/               sous-agents de /recette : qa-automatisation, qa-cahier, qa-manuel
├── docs/
│   ├── GUIDE-UTILISATION.md     à quoi sert chaque document, qui l'écrit, comment l'utiliser
│   ├── TECHNIQUES-ISTQB.md      techniques de conception et types de test autorisés (référentiel)
│   ├── FORMAT-CAS-DE-TESTS.md   format des fichiers d'analyse et règles de contrôle
│   ├── OPENCODE.md              guide de l'équipe sous OpenCode
│   └── regles-livrables.md      règles de rédaction du manuel et du cahier
├── outils/                   scripts Python sans réseau (création, relecture, contrôle, cahier, specs,
│                             statut, vérification du poste, synchronisation OpenCode)
├── templates/                modèles Excel, Word, specs, socle Playwright, exemples
└── projets/
    └── saucedemo/            projet d'exemple : CDC et analyse produite (02-a-valider)
```

## Outils en ligne de commande

Utilisables sans agent :

```powershell
python outils/nouveau_projet.py <nom> --url <URL> --squash-id <ID> --libelle "<Nom>"
python outils/rendre_revue.py <projet>                  # vues md, Excel et Word depuis le JSON
python outils/synchroniser_vues.py <projet>             # importe l'Excel ou le Word modifié, régénère le reste
python outils/controle.py <projet> [--dossier 03-valide] # contrôle + matrice de traçabilité
python outils/build_cahier.py <projet> [--nominaux]      # cahier Excel, temps B (exige l'URL et l'exploration)
python outils/generer_specs.py <projet>                  # specs BROUILLON (depuis 03-valide)
python outils/statut.py [projet]
python outils/verifier_installation.py
python outils/synchroniser_opencode.py                  # après modification d'une commande
```

## Garde-fous

- Rien n'est publié ni généré depuis `02-a-valider` : seul ce que le responsable du projet a déplacé dans `03-valide` compte.
- Squash : simulation d'abord, publication réelle après accord ; aucune suppression possible (bloquée dans le MCP et dans `.claude/settings.json`).
- Aucune donnée inventée : un manque du cahier des charges devient une question (`ambiguites.md`).
- Conception ISTQB contrôlée : une technique ou un type de test hors référentiel, ou un type de test non examiné dans la stratégie, est une erreur de `outils/controle.py`.
- Aucun secret dans les fichiers : identifiants par variables d'environnement.
- Le cahier de tests et le manuel ne sont jamais produits avant que la plateforme soit accessible et explorée.

## Limites connues

- L'agent ne surveille pas les dossiers : chaque étape se lance par une commande.
- Un cas déjà publié et modifié ensuite n'est pas mis à jour dans Squash (à faire à la main ; l'agent liste les cas concernés).
- Cahier de tests : version française uniquement pour l'instant.
- Les cahiers des charges sont envoyés au modèle d'IA : vérifier que le client l'autorise.
