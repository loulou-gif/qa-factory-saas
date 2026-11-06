# QA Factory

> **Dépôt `qa-factory-saas`** : en plus de l'usage sur poste décrit ci-dessous, ce dépôt contient la version serveur (application web interne) dans `saas/`. Installation, exploitation et état d'avancement : `saas/README.md`.

Chaîne de production des livrables de test, pilotée par un agent IA (**Claude Code** ou **OpenCode**) relié à Squash TM et à un navigateur :

**cahier des charges → cas de tests + questions + jeux de données → relecture et validation → Squash TM + specs d'automatisation → (plateforme disponible) → exploration → en parallèle : tests Playwright, cahier de tests, manuel utilisateur.**

Ce que l'équipe y gagne :
- **Des cas de tests conçus uniquement avec les techniques ISTQB** (partitions d'équivalence, valeurs limites, tables de décision, transitions d'états, cas d'utilisation, critères d'acceptation, estimation d'erreurs…). Chaque cas indique sa technique, son type de test et sa nature.
- **Les types de tests à effectuer** : fonctionnel, performance, sécurité, utilisabilité, compatibilité, fiabilité, maintenabilité, portabilité, confirmation et régression. Chacun est déclaré retenu, à confirmer (avec une question au client) ou non retenu, avec sa justification.
- **Les cas de tests en Excel et en Word**, modifiables directement par un QA qui ne touche pas au code. L'agent reporte ses modifications partout.
- **Rien d'inventé** : ce que le cahier des charges ne dit pas devient une question au client.
- **Une seule source** (`cas-de-tests.json`) dont sont générés Squash, le cahier de tests, les specs et les tests, avec les mêmes identifiants (`EX-001`, `CT0001`).

Documentation :
| Document | Pour |
|---|---|
| `docs/GUIDE-UTILISATION.md` | **À lire en premier** : à quoi sert chaque document, qui l'écrit, comment l'utiliser |
| `docs/TECHNIQUES-ISTQB.md` | Les techniques de conception et types de test autorisés, avec leurs références au syllabus |
| `docs/OPENCODE.md` | Installation et utilisation avec OpenCode |
| `docs/FORMAT-CAS-DE-TESTS.md` | Format exact des fichiers et liste des contrôles (spécialistes) |
| `docs/regles-livrables.md` | Règles de rédaction du manuel et du cahier |

## Le parcours

| Étape | Qui | Commande dans l'agent | Résultat |
|---|---|---|---|
| 1. Créer le projet | Responsable | `/nouveau-projet sauce-test https://www.saucedemo.com 28` | `projets/sauce-test/` prêt à l'emploi |
| 2. Déposer les documents | Responsable | explorateur Windows | CDC, US, DSF, maquettes dans `01-entrant/` |
| 3. Analyser | Agent | `/analyser sauce-test` | dans `02-a-valider/` : cas de tests (JSON, Excel, Word, Markdown), stratégie de types de tests, questions, jeux de données |
| 4. Relire, corriger | Responsable + agent | modifier l'Excel **ou** le Word, puis `/corriger sauce-test` ; ou `/corriger sauce-test <demande>` | nouvelle version, tous les fichiers à jour |
| 5. **Valider** | **Responsable** | **déplacer tout le contenu de `02-a-valider/` dans `03-valide/`** | validation |
| 6. Publier dans Squash | Agent, avec l'accord du responsable | `/publier sauce-test` | simulation, puis exigences et cas liés dans Squash |
| 7. Specs d'automatisation | Agent | `/specs sauce-test` | specs BROUILLON dans `04-livrables/specs/` |
| 8. Explorer la plateforme | Agent | `/explorer sauce-test` | découvertes, écarts, specs CONFIRMÉES |
| 9. Recette, en parallèle | Agent | `/recette sauce-test` | tests Playwright exécutés + cahier de tests Excel + manuel Word |
| (ou séparément) | Agent | `/generer-tests`, `/cahier`, `/manuel` | un seul de ces livrables |
| Suivi | — | `/statut` | avancement de chaque projet |

Les commandes peuvent aussi être formulées en phrases (« crée-moi un nouveau projet sauce-test… ») ; la forme `/commande` est plus sûre.

**Deux temps :**
- **Temps A (étapes 1 à 7)** : le cahier des charges suffit. C'est le cas courant : on écrit les tests pendant que le site se développe. Si le site n'existe pas encore, créer le projet sans adresse : `/nouveau-projet mon-projet 28` (ou `/nouveau-projet mon-projet` si le projet Squash n'existe pas encore).
- **Temps B (étapes 8 et 9)** : il faut le lien de la plateforme, l'environnement et les comptes de test. Le jour où le site est livré : « Le site du projet mon-projet est disponible à l'adresse https://…, mets à jour la fiche du projet ». **Le cahier de tests et le manuel ne sont produits qu'en temps B**, en parallèle des scripts automatisés ; avant, l'agent refuse.

## Les cas de tests : quatre formats, une seule vérité

| Fichier (dans `02-a-valider/`) | Pour quoi faire | Modifiable ? |
|---|---|---|
| `cas-de-tests.xlsx` | Relire et corriger dans Excel : filtres, tri, listes déroulantes (nature, type de test, technique ISTQB, importance) | **Oui** |
| `cas-de-tests.docx` | Relire et corriger dans Word : une fiche par cas, facile à imprimer ou à commenter | **Oui** |
| `cas-de-tests.md` | Relire en texte (éditeur, GitHub) | Non, régénéré |
| `cas-de-tests.json` | La source, lue par Squash et les outils | Spécialistes |

Pour corriger :
1. Ouvrir **l'Excel ou le Word** (pas les deux), modifier, enregistrer, **fermer**.
2. Dans l'agent : `/corriger <projet>`.
3. L'agent repère le fichier modifié, reporte les changements dans le JSON (version + 1), régénère les autres fichiers, lance le contrôle et résume ce qu'il a pris en compte (cas ajoutés, modifiés, supprimés).

Si l'Excel et le Word ont été modifiés différemment, l'agent n'écrit rien et demande lequel garder. Les règles de saisie (ajouter un cas ou une étape, supprimer) sont dans la feuille « Lisez-moi » de l'Excel, en tête du Word et dans `docs/GUIDE-UTILISATION.md`.

## Organisation d'un projet

```text
projets/<projet>/
├── projet.json         fiche du projet : client, responsable, URL, environnement, ID Squash, actions autorisées
├── journal.md          historique des étapes
├── 01-entrant/         documents du client
├── 02-a-valider/       analyse proposée par l'agent : cas (json, xlsx, docx, md), ambiguites.md,
│                       jeux-de-donnees.md, matrice-tracabilite.md
├── 03-valide/          la même chose, une fois validée par le responsable
└── 04-livrables/       squash/ (correspondance), specs/, exploration/, cahier/, manuel/
```

## Installation (une fois par poste)

Même dépôt pour Claude Code et OpenCode ; détails OpenCode dans `docs/OPENCODE.md`.

1. **Programmes** : Claude Code ou OpenCode, Node.js 20+, Python 3, Pandoc, puis :
   ```bash
   pip install openpyxl python-docx
   ```
2. **Le MCP Squash** : récupérer `squash-tm-mcp`, puis dans son dossier `npm install` et `npm run build`.
3. **Variables d'environnement** (lues par `.mcp.json` pour Claude Code et `opencode.json` pour OpenCode ; aucun identifiant n'est écrit dans le dépôt) :
   ```bash
   setx SQUASH_MCP_INDEX "C:/chemin/vers/squash-tm-mcp/dist/index.js"   # avec des /, sinon opencode.json devient invalide
   setx SQUASH_TM_BASE_URL "https://squash.smile.ci/squash/api/rest/latest"
   ```
   Puis l'authentification Squash, au choix :
   - **jeton d'API** (Squash → Mon compte → Jetons d'API) : `setx SQUASH_TM_API_TOKEN "<jeton>"` ;
   - **identifiant et mot de passe**, si Squash affiche « Aucun secret JWT n'est défini pour cette instance » (jetons non activés par l'administrateur) :
     ```bash
     setx SQUASH_TM_USERNAME "<identifiant Squash>"
     setx SQUASH_TM_PASSWORD "<mot de passe Squash>"
     ```
   Si les deux sont définis, le jeton est prioritaire.

   Pour le temps B, les comptes de test de l'application : `setx APP_USERNAME "…"` et `setx APP_PASSWORD "…"`.
4. **Fermer le terminal et en ouvrir un nouveau** : `setx` ne s'applique qu'aux fenêtres ouvertes après. Avec le terminal intégré de VS Code, quitter VS Code complètement.
5. **Vérifier le poste**, depuis le dossier `qa-factory` :
   ```bash
   python outils/verifier_installation.py
   ```
   Attendu : « Bilan : 0 point(s) bloquant(s). Poste prêt. »
6. **Lancer l'agent dans ce même terminal** : `claude` (ou `opencode`). Accepter les serveurs `squash-tm` et `playwright`, puis taper `/mcp` : les deux doivent être connectés. Test : « Lis le projet Squash 28 avec get_project ».

`setx` fonctionne dans PowerShell comme dans Git Bash. Seuls les chemins diffèrent : `cd C:\Users\...` dans PowerShell, `cd ~/Desktop/...` (avec des `/`) dans Git Bash.

## Premier essai

Avec le projet d'exemple SauceDemo, dont le cahier des charges est fourni :
1. `/nouveau-projet sauce-test https://www.saucedemo.com 28`
2. Copier `projets/saucedemo/01-entrant/cahier-des-charges.md` dans `projets/sauce-test/01-entrant/`.
3. `/analyser sauce-test`, puis ouvrir `projets/sauce-test/02-a-valider/cas-de-tests.xlsx`.
4. Modifier un titre dans l'Excel, fermer, `/corriger sauce-test` : le Word et le Markdown sont mis à jour.

Une analyse de référence est déjà dans `projets/saucedemo/02-a-valider/` pour comparer.

## En cas de problème

| Symptôme | Cause et solution |
|---|---|
| `verifier_installation.py` : une variable en KO | Variable non définie, ou terminal ouvert avant le `setx` : refaire le `setx`, ouvrir un nouveau terminal |
| `/mcp` : `squash-tm` « failed » ou « Connection closed » | L'agent a été lancé depuis un terminal qui ne voit pas les variables (souvent VS Code ouvert avant le `setx`) : tout fermer, nouveau terminal, relancer `claude` |
| Erreur 401 dans Squash | Identifiant, mot de passe ou jeton incorrect |
| « Aucun secret JWT n'est défini pour cette instance » | Les jetons d'API ne sont pas activés sur Squash : utiliser identifiant et mot de passe (installation, étape 3) |
| `/corriger` : « fichier ouvert » | Fermer l'Excel ou le Word puis relancer |
| `/corriger` : conflit | L'Excel et le Word ont été modifiés tous les deux : choisir lequel garder |
| `/cahier` ou `/manuel` refusé | Temps B non atteint : URL du site absente de `projet.json`, ou exploration non faite |

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
│   ├── commands/             source des commandes (/analyser, /corriger, /publier, /specs, /explorer, /recette…)
│   └── skills/               les 7 skills, partagées par Claude Code et OpenCode
├── .opencode/
│   ├── commands/             commandes OpenCode, générées depuis .claude/commands
│   └── agents/               sous-agents de /recette : qa-automatisation, qa-cahier, qa-manuel
├── docs/                     guide d'utilisation, référentiel ISTQB, format, OpenCode, règles des livrables
├── outils/                   scripts Python sans réseau (voir ci-dessous)
├── templates/                modèles Excel, Word, specs, socle Playwright, exemples
└── projets/
    └── saucedemo/            projet d'exemple : cahier des charges et analyse produite
```

## Outils en ligne de commande

Utilisables sans agent, depuis le dossier `qa-factory` :

```bash
python outils/nouveau_projet.py <nom> [--url <URL>] [--squash-id <ID>] [--libelle "<Nom>"] [--responsable "<Nom>"]
python outils/rendre_revue.py <projet>         # vues md, Excel et Word depuis le JSON (refuse d'écraser des modifications non reprises)
python outils/synchroniser_vues.py <projet>    # reprend l'Excel ou le Word modifié, régénère le reste (--source en cas de conflit)
python outils/controle.py <projet> [--dossier 03-valide]   # contrôle + matrice de traçabilité
python outils/build_cahier.py <projet> [--nominaux]        # cahier de tests Excel, temps B (exige l'URL et l'exploration)
python outils/generer_specs.py <projet>        # specs BROUILLON (depuis 03-valide)
python outils/statut.py [projet]
python outils/verifier_installation.py
python outils/synchroniser_opencode.py         # après modification d'une commande dans .claude/commands
```

## Garde-fous

- **Validation humaine** : rien n'est publié ni généré depuis `02-a-valider` ; seul ce que le responsable du projet a déplacé dans `03-valide` compte. L'agent ne valide jamais à sa place.
- **Squash** : simulation d'abord, publication réelle après accord explicite ; aucune suppression possible (bloquée dans le MCP et dans la configuration des deux agents).
- **Rien d'inventé** : un manque du cahier des charges devient une question (`ambiguites.md`) ; un type de test sans seuil mesurable reste « à confirmer ».
- **Conception ISTQB contrôlée** : une technique ou un type de test hors référentiel, ou un type de test non examiné dans la stratégie, est une erreur du contrôle.
- **Modifications manuelles protégées** : une régénération qui écraserait des modifications de l'Excel ou du Word non reprises est refusée ; un Excel ou un Word modifié après validation est signalé.
- **Aucun secret dans le dépôt** : identifiants Squash et comptes de test par variables d'environnement.
- **Temps B** : le cahier de tests et le manuel ne sont jamais produits avant que la plateforme soit accessible et explorée.

## Limites connues

- L'agent ne surveille pas les dossiers : chaque étape se lance par une commande.
- Des modifications faites à la fois dans l'Excel et dans le Word ne sont pas fusionnées automatiquement : il faut choisir l'un des deux (l'agent peut reporter l'autre à la main).
- Les questions (`ambiguites.md`) et les jeux de données (`jeux-de-donnees.md`) restent en Markdown.
- Un cas déjà publié puis modifié n'est pas mis à jour dans Squash (à faire à la main ; l'agent liste les cas concernés).
- Cahier de tests : version française uniquement pour l'instant.
- Les cahiers des charges sont envoyés au modèle d'IA : vérifier que le client l'autorise.
- Les projets (`projets/<nom>/`) ne sont pas envoyés sur Git, à l'exception de l'exemple `saucedemo` (voir `.gitignore`) : ils restent sur le poste qui les a créés. Conséquence : le fichier `04-livrables/squash/correspondance.json`, qui évite les doublons dans Squash, n'est pas partagé. **Un projet doit donc toujours être publié depuis le même poste**, ou ce fichier doit être transmis à la main. Sauvegarder le dossier `projets/` par un autre moyen (OneDrive, serveur de fichiers).
