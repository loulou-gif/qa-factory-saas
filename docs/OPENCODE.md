# QA Factory avec OpenCode — guide de l'équipe

Même dépôt, mêmes règles, mêmes skills, mêmes commandes que sous Claude Code. Seule la configuration change, et elle est déjà dans le dépôt : chaque testeur n'a qu'à installer les programmes et définir trois variables d'environnement.

## 1. Ce qu'OpenCode utilise dans le dépôt

| Fichier | Rôle |
|---|---|
| `AGENTS.md` | Règles et workflow (lu automatiquement par OpenCode) |
| `opencode.json` | Serveurs MCP `squash-tm` et `playwright`, outils destructifs désactivés, permissions |
| `.claude/skills/*/SKILL.md` | Les 7 skills, lues par OpenCode comme par Claude Code |
| `.opencode/commands/*.md` | Les commandes `/analyser`, `/publier`, `/recette`… |
| `.opencode/agents/qa-*.md` | Les 3 sous-agents de `/recette` : `qa-automatisation`, `qa-cahier`, `qa-manuel` |
| `outils/`, `templates/`, `docs/` | Partagés, identiques pour les deux outils |

## 2. Installation d'un poste (une fois, environ 20 minutes)

1. **Programmes** : OpenCode, Node.js 20 ou plus, Python 3 avec `pip install openpyxl`, Pandoc. Un modèle d'IA configuré dans OpenCode (fournisseur et clé, selon la politique de l'équipe).
2. **Récupérer les deux dépôts** :
   - `qa-factory` (ce dépôt) ;
   - `squash-tm-mcp` (le MCP Squash amélioré), puis dans son dossier : `npm install` et `npm run build`.
3. **Créer un jeton Squash personnel** : Squash → Mon compte → Jetons d'API, droits lecture et écriture. Un jeton par testeur : les créations dans Squash portent ainsi le nom de leur auteur.
4. **Définir les variables d'environnement** (PowerShell, une fois, puis rouvrir le terminal) :
   ```powershell
   setx SQUASH_MCP_INDEX "C:\chemin\vers\squash-tm-mcp\dist\index.js"
   setx SQUASH_TM_BASE_URL "https://squash.smile.ci/squash/api/rest/latest"
   setx SQUASH_TM_API_TOKEN "<ton jeton>"
   ```
   Le jeton n'est jamais écrit dans un fichier du dépôt : `opencode.json` le lit avec `{env:SQUASH_TM_API_TOKEN}`.
   Si Squash refuse de créer le jeton avec le message « Aucun secret JWT n'est défini pour cette instance », l'administrateur Squash n'a pas activé les jetons d'API. En attendant, utiliser son identifiant et son mot de passe Squash à la place du jeton (le MCP passe alors en authentification Basic) :
   ```powershell
   setx SQUASH_TM_USERNAME "<identifiant Squash>"
   setx SQUASH_TM_PASSWORD "<mot de passe Squash>"
   ```
   Ces valeurs restent dans les variables d'environnement du poste, jamais dans le dépôt. Si les deux modes sont définis, le jeton est prioritaire.
5. **Vérifier le poste** : `python outils/verifier_installation.py` doit finir par « Poste prêt ».
6. **Lancer OpenCode** dans le dossier `qa-factory` : `opencode`. Vérifier que les serveurs MCP `squash-tm` et `playwright` apparaissent comme connectés, puis taper `/statut`.

Derrière un proxy d'entreprise, si le MCP Squash n'arrive pas à joindre Squash : ajouter `"NODE_USE_ENV_PROXY": "1"` dans `opencode.json` → `mcp.squash-tm.environment` sur le poste concerné (Node 22.21 ou plus).

## 3. Utilisation

Identique à Claude Code (voir `README.md`) :

| Temps | Commandes |
|---|---|
| A — cahier des charges reçu | `/nouveau-projet`, `/analyser`, `/corriger`, validation (déplacer les 4 fichiers dans `03-valide`), `/publier`, `/specs` |
| B — plateforme accessible | `/explorer`, puis `/recette` (scripts, cahier et manuel en parallèle) ou `/generer-tests`, `/cahier`, `/manuel` séparément |
| Suivi | `/statut` |

Avec OpenCode :
- les commandes prennent leurs arguments après le nom : `/analyser saucedemo` ;
- `/recette` délègue aux sous-agents `qa-automatisation`, `qa-cahier` et `qa-manuel` avec l'outil task ; on peut aussi appeler l'un d'eux directement en le mentionnant : `@qa-cahier génère le cahier du projet saucedemo` ;
- la skill citée par une commande est chargée par l'agent avec l'outil `skill`.

## 4. Garde-fous dans `opencode.json`

| Réglage | Effet |
|---|---|
| `tools` : `squash-tm_delete_*`, `squash-tm_unlink_*`, `squash-tm_sync_feature_to_squash`, `squash-tm_create_project*` à `false` | Ces outils n'existent pas pour l'agent : aucune suppression ni création de projet dans Squash |
| `permission.bash` : `*` à `ask`, scripts `python outils/*` autorisés, `rm` et `del` interdits | L'agent demande avant toute autre commande système |
| `permission.external_directory` à `ask` | L'agent demande avant d'écrire hors de `qa-factory` (dépôt d'automatisation, par exemple) |
| `permission.webfetch` à `ask` | Pas de consultation web sans accord |
| `permission` : `squash-tm_publish_validated_test_cases` et tous les outils Squash qui créent ou modifient à `ask` | OpenCode demande confirmation avant chaque écriture dans Squash ; les lectures passent sans question |

En plus de cette confirmation, la règle du dépôt s'applique : simulation, plan présenté, puis publication réelle seulement après l'accord explicite du responsable du projet.

Vérification faite avec OpenCode 1.19.5 (`opencode debug config`, `opencode debug skill`, `opencode debug agent`) : les deux serveurs MCP, les variables d'environnement, les 11 commandes, les 3 sous-agents, les 7 skills et les permissions sont bien pris en compte.

## 5. Travailler à plusieurs sur le même dépôt

- **Un projet, un responsable** (`projet.json` → `responsable`) : c'est lui qui valide en déplaçant les fichiers dans `03-valide`.
- **Git** : committer après chaque étape (analyse, validation, publication, livrables). La validation devient un commit traçable : qui a validé quoi, et quand.
- **Fichier de correspondance Squash** (`04-livrables/squash/correspondance.json`) : toujours le committer et le récupérer (`git pull`) avant de publier. Deux testeurs qui publient le même projet sans ce fichier à jour créent des doublons.
- **Commandes** : la source est `.claude/commands/`. Après une modification, lancer `python outils/synchroniser_opencode.py` et committer les deux dossiers. Les commandes propres à OpenCode (`/recette`) sont dans `outils/opencode/`.
- **Skills** : un seul exemplaire, dans `.claude/skills/`, partagé par les deux outils.

## 6. Différences connues avec Claude Code

- Sous-agents en parallèle : `/recette` lance les trois appels task dans le même message. Selon la version d'OpenCode et le modèle utilisé, ils s'exécutent en parallèle ou l'un après l'autre ; le résultat est le même, seule la durée change.
- Qualité : les skills sont écrites pour des modèles capables de suivre des consignes longues. Avec un modèle plus léger, vérifier particulièrement l'analyse (`/analyser`) et lancer le contrôle à chaque étape.
- La commande `cmd /c npx` du MCP Playwright est prévue pour Windows. Sur macOS ou Linux, remplacer par `["npx", "@playwright/mcp@latest"]` dans `opencode.json` (et dans `.mcp.json` pour Claude Code).
