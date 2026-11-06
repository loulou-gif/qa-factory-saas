# QA Factory SaaS (version serveur)

Application web interne : les testeurs utilisent QA Factory depuis un navigateur, sans rien installer. Elle pilote le même moteur que `qa-factory` (skills, règles ISTQB, scripts, MCP Squash), installé une seule fois sur un serveur.

État : **phases 1 et 2** de la feuille de route (moteur sur serveur, temps A complet), plus le temps B dans l'application : tests de l'application par l'assistant, mise à jour de Squash, automatisation Playwright et exécution des scripts. L'exploration libre, le cahier de tests et le manuel se font encore avec `qa-factory` sur un poste.

## Ce que fait l'application

Un parcours simple, sans formation (règles de conception : skill `interface-qa-factory`, couleurs de Synelia) :

1. **Accueil** : un seul rectangle de dépôt. Déposer le cahier des charges (un ou plusieurs fichiers : pdf, docx, doc, odt, md, txt, xlsx, png, jpg) **lance directement l'analyse** ; le projet prend le nom du fichier.
2. **Génération** : le rectangle se remplit jusqu'à 100 %, affiche « Génération terminée » puis ouvre les fichiers produits. Aucune demande d'accord n'est présentée : tout se déroule en arrière-plan.
3. **Fichiers produits** : cas de tests, questions pour le client, jeux de données, chacun résumé en une ligne ; Excel et Word en téléchargement.
4. **Relecture** : les cas, groupés par fonctionnalité en onglets, se lisent replié (une ligne par cas) et se modifient sur place (titre, prérequis, étapes « Je fais » / « Je dois voir »). **« Enregistrer » enregistre et valide** : la version passe dans `03-valide`, les specs d'automatisation sont générées. Il n'y a plus d'étape de validation par un responsable. « Modifier à nouveau les cas » rouvre la relecture si besoin.

5. **Questions pour le client** : chaque question se renseigne sur place (« Enregistrer la réponse ») ou se classe « Sans objet (faux positif) ». En relecture, « Mettre à jour les cas avec les réponses » fait reporter les réponses dans les cas par l'assistant.
6. **Jeux de données** : valeurs, remarques et champs se modifient sur place (pas de mot de passe réel : « variable NOM »).

Puis **Envoyer dans Squash** : on choisit le projet Squash dans un champ de recherche qui liste les projets visibles avec son compte (une partie du nom ou le numéro suffit, au clavier ou à la souris) et, si on le connaît, le lien de l'application testée (enregistré dans `projet.json`). L'application vérifie ce qui existe, annonce ce qui sera créé, puis envoie après confirmation, avec une barre de progression réelle. **Arrêter l'envoi** l'interrompt avant l'élément suivant ; une relance reprend la suite, sans doublon.

Chaque utilisateur connecte son Squash dans **Paramètres › Connexion Squash**. Le jeton d'API personnel est proposé par défaut (révocable, avec date d'expiration) ; identifiant et mot de passe restent possibles. Sur le service public, une adresse Squash qui mène à un réseau interne est refusée, y compris si le nom change de réponse entre le contrôle et la connexion (`reseau_public.mjs`).
- Les cas suspendus à une **question bloquante encore ouverte** ne partent pas ; dès que la question est répondue ou classée sans objet, la page propose « Envoyer N nouveaux cas dans Squash ».
- Chaque jeu de données devient, sur le cas, un **jeu de données Squash** (nom `JDD-004 Informations de livraison valides`) avec ses **paramètres** et leurs valeurs ; le prérequis du cas cite les paramètres (`Prénom = ${Prenom}`), pour que Squash affiche les valeurs du jeu choisi à l'exécution.
- **Premier envoi** : tout est rangé dans un dossier « QA Factory - <nom du projet> », créé côté exigences et côté cas de tests. Le reste du projet Squash n'est jamais touché, même s'il contient déjà des éléments de mêmes références (autre outil, ancienne publication).
- **Mise à jour de Squash** : quand des cas déjà envoyés changent dans QA Factory (corrections après les tests de l'application, nouvelle relecture), la page du projet l'indique (« N éléments modifiés depuis le dernier envoi ») et propose **Mettre à jour Squash**. Seuls les éléments créés par QA Factory sont concernés, et **rien n'est réécrit ni supprimé** : un élément changé reçoit une **nouvelle version** (`CT0002.1`, puis `CT0002.2`...) dans le même dossier, et l'ancienne passe en **Obsolète**, telle quelle, pour la traçabilité. Champ par champ :
  - un champ changé seulement dans QA Factory prend la valeur de QA Factory dans la nouvelle version ;
  - un champ changé dans Squash par quelqu'un est conservé (recopié dans la nouvelle version s'il y en a une) ;
  - un champ changé des deux côtés est montré avec les deux versions : Squash est gardé, sauf si l'on coche « Remplacer par la version QA Factory ».
  Quand une exigence reçoit une nouvelle version, les cas qui la couvrent sont liés aussi à la nouvelle. Un élément de même référence (CT0001, EX-001) présent dans le dossier QA Factory sans avoir été créé par QA Factory n'est ni créé ni modifié : il est signalé. Un passage en Obsolète qui échoue est signalé et retenté au prochain envoi.
- Jeux de données : un jeu qui a déjà une valeur dans Squash n'est pas touché, seuls les jeux encore vides sont complétés ; une relance ne crée aucun doublon.

### Temps B : tester l'application et automatiser

Plan et décisions : [docs/PLAN-TEMPS-B.md](../docs/PLAN-TEMPS-B.md). Une fois les cas validés et le lien de l'application renseigné (page **Application testée**, avec des comptes de test chiffrés) :
1. **Tester l'application** : l'assistant exécute les cas dans un navigateur propre à la tâche, limité aux domaines de l'application ; il ne voit jamais les mots de passe (il saisit le nom du secret). Résultats, rapport HTML/Excel et corrections de cas proposées, à accepter ou non.
2. **Mettre à jour Squash** avec les cas corrigés (nouvelle version, l'ancienne passe en Obsolète).
3. **Automatiser** : l'application classe les scénarios (criticité, usage, stabilité observée, coût) ; le testeur coche, choisit JavaScript ou TypeScript, et l'assistant écrit les scripts Playwright dans le dépôt du projet (`projets/<projet>/05-automatisation/`) en relevant les locators réels.
4. **Exécuter les scripts**, sans IA : Playwright lance les tests avec les comptes du projet. Avant, les fichiers du gabarit sont rétablis et les scripts contrôlés (pas d'import autre que Playwright et le dépôt, pas d'accès système ni réseau hors du navigateur, pas d'adresse hors de l'application) ; le navigateur ne résout que les domaines de l'application ; le processus ne reçoit que l'URL et les comptes ; les traces sont désactivées et les secrets retirés des rapports. Résultats par scénario, **rapport Playwright**, inventaire `docs/test-inventory.md` mis à jour, **archive .zip** du dépôt (sans `.env`) pour le reprendre sur un poste.

5. **Documents de recette** (page du projet › Documents de recette) :
   - **Cahier de tests** (Excel), produit sans IA à partir des cas validés, tous les cas ou les nominaux seulement ;
   - **Manuel utilisateur** (Word) : l'assistant parcourt l'application avec les comptes du projet (fonctionnalités cochées), prend les captures et écrit le contenu (`contenu.json`, des données, jamais du code) ; l'application le contrôle (secrets masqués, captures vérifiées) puis le met en page. Les points non observés sont listés dans `points_a_confirmer_manuel.md`. « Refaire la mise en page » reprend la dernière rédaction dans le modèle actuel, sans relancer l'IA.

### Menu et paramètres

Un menu latéral à gauche (tiroir sur téléphone) : **Nouvelle analyse**, **Projets**, **Activité** (les tâches de tous les projets), et en bas, au-dessus de l'utilisateur connecté, **Paramètres**, une page qui regroupe :
- **Connexion Squash** : propre à chaque utilisateur ;
- **Modèles d'IA** : listes déroulantes des modèles connus (gratuits avec une clé gratuite, gratuits sans clé, payants), ou saisie libre d'un identifiant. Fournisseurs : Google Gemini, OpenRouter, Groq, Cerebras, Mistral, DeepSeek, Anthropic, OpenAI, et OpenCode (gratuit, sans clé).
  - l'administrateur règle un modèle principal, un modèle par usage (analyse, tests, automatisation, documents) et jusqu'à 5 **modèles de secours** : quand un modèle atteint sa limite (quota gratuit, crédit épuisé, clé absente ou refusée, fournisseur qui ne répond pas), la tâche continue avec le suivant dans la même session, sans rien refaire ; le journal de la tâche l'indique ;
  - les **modèles gratuits partagés** (OpenRouter « :free », OpenCode) ne sont utilisés que si l'administrateur coche leur autorisation : leurs fournisseurs peuvent garder les documents envoyés pour entraîner leurs modèles (même remarque pour les offres gratuites de Google et de Mistral) ;
  - **clés** : celles de l'entreprise (administrateur) et les **clés personnelles** de chaque utilisateur, utilisées en priorité pour les tâches qu'il lance (le relais retrouve l'utilisateur par la session du moteur). Avec une clé Gemini gratuite par personne, chacun a son propre quota gratuit. Clés chiffrées en base, seuls les 4 derniers caractères affichés ;
  - chaque modèle et chaque nouvelle clé reçoivent un court essai avant l'enregistrement ; une clé refusée annule l'enregistrement, une clé absente ou une limite atteinte est seulement signalée. Ce qui n'est pas renseigné reprend les réglages du serveur (`QAF_MODELE`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`…) ;
- **Modèles de documents** : le modèle Excel du cahier et le modèle Word du manuel de l'entreprise. Sans modèle déposé, les modèles internes servent. Le dépôt est analysé et le résultat affiché (colonnes reconnues, marqueurs, avertissements) ; les fichiers avec macros sont refusés ;
- **Équipe** (administrateur) et **Mon compte**.

Modèles d'entreprise :
- **cahier (.xlsx)** : la ligne d'en-têtes du tableau est repérée par ses libellés (« Réf. », « Action à réaliser », « Résultat attendu »… avec ou sans accents ni pluriels) ; une ligne par étape quand il y a une colonne d'étape ou de numéro d'étape, sinon une ligne par cas ; la mise en forme de la première ligne sous les en-têtes est reprise ; « Résultat obtenu », « Statut », « Commentaire » restent vides. Marqueurs remplacés partout : `{{PROJET}}`, `{{TITRE}}`, `{{VERSION}}`, `{{DATE}}`, `{{AUTEUR}}`, `{{CONTACT}}`, `{{CLIENT}}`, `{{URL}}`, `{{DESCRIPTION}}`, `{{NB_CAS}}`, `{{ENVIRONNEMENT}}` ;
- **manuel (.docx)** : le contenu se place à `{{CONTENU}}` (sinon à la fin), le sommaire à `{{SOMMAIRE}}` ; les titres, légendes et paragraphes prennent les styles du modèle (Titre 1 à 3, Légende) ; marqueurs `{{PROJET}}`, `{{TITRE}}`, `{{SOUS_TITRE}}`, `{{VERSION}}`, `{{DATE}}`, `{{AUTEUR}}`, `{{CLIENT}}`, `{{URL}}`, y compris dans les en-têtes et pieds de page.

**Relais IA** : le moteur ne reçoit jamais les clés d'API. Ses fournisseurs pointent vers l'application (`/ia/<fournisseur>/…`, jeton interne dérivé de `OPENCODE_SERVER_PASSWORD`), qui ne laisse passer que les routes d'inférence, ajoute la clé (celle des Paramètres, sinon celle du serveur) et relaie la réponse au fil de l'eau.

Playwright (`/opt/qaf-playwright`, variable `QAF_PLAYWRIGHT_DIR`) et le MCP Playwright (`/opt/qaf-playwright-mcp`) sont installés dans l'image à versions figées, chacun avec son Chromium ; les dépôts des projets n'ont pas de `node_modules`.

Garde-fous propres à la version serveur :
- l'agent IA n'a **aucun** accès à Squash (le MCP squash-tm est désactivé pour lui), ni au web, ni hors du dépôt ; l'envoi dans Squash passe uniquement par le bouton, avec le code de publication du MCP ;
- aucune demande d'accord technique n'est posée au testeur : les commandes utiles à l'analyse (scripts Python du dépôt, création de dossiers, lecture et conversion de documents) sont autorisées d'avance ; tout le reste (suppression, déplacement, réseau, installation, lecture des variables d'environnement) est refusé automatiquement, l'assistant continue sans, et le refus est noté dans le journal de la tâche. Liste dans `opencode.serveur.json` ;
- une seule tâche à la fois par projet ; le coût OpenRouter de chaque analyse est enregistré ;
- « Enregistrer » refuse de valider si le contrôle ISTQB signale des erreurs ;
- comptes nominatifs, mots de passe hachés, mot de passe provisoire à changer, protection CSRF, journal d'audit (qui a validé, qui a envoyé dans Squash).

### Lancer l'application sur un poste (sans Docker)

Sur un poste avec Python, Node et OpenCode, depuis le dossier du dépôt :
```bash
pip install -r saas/requirements.txt

# 1. Avec une clé OpenRouter (Git Bash ; dans PowerShell : $env:OPENROUTER_API_KEY = "sk-or-...")
export OPENROUTER_API_KEY="sk-or-..."
python saas/dev/demo.py --modele openrouter/anthropic/claude-sonnet-4.5

# 2. Avec un modèle gratuit d'OpenCode, sans clé
python saas/dev/demo.py --modele opencode/deepseek-v4.1-flash-free

# 3. Sans IA (faux modèle qui rejoue l'analyse de SauceDemo)
python saas/dev/demo.py --simulation
```
Le navigateur s'ouvre sur `http://127.0.0.1:8000` ; identifiant `demo`, mot de passe `Demo-2026-qa` (à changer à la première connexion). Liste des modèles : `opencode models openrouter`, `opencode models opencode`. Pour essayer l'envoi dans Squash : compiler le MCP à côté du dépôt (`cd ../squash-tm-mcp && npm install && npm run build`, ou définir `SQUASH_MCP_DIR`), puis régler sa connexion dans l'application (**Paramètres › Squash**), sur un projet Squash d'essai.

Choisir le modèle :
- **Clé OpenRouter** : la voie prévue pour le serveur. Créer une clé dédiée avec un plafond mensuel, activer Zero Data Retention dans les réglages de confidentialité du compte OpenRouter.
- **Modèles gratuits d'OpenCode** : sans clé, mais offre limitée dans le temps, qualité nettement inférieure pour une analyse aussi exigeante, et certains peuvent réutiliser les données pour l'entraînement : n'y mettre aucun cahier des charges client. Parmi eux, GLM-5.3-Flash Free et DeepSeek V4.1 Flash Free sont annoncés sans conservation des données.
- **Abonnement Claude (Pro, Max)** : impossible dans OpenCode. Depuis 2026, Anthropic réserve l'abonnement à Claude Code et Claude.ai ; tout autre outil passe par une clé API facturée à l'usage. Pour utiliser l'abonnement, rester sur `qa-factory` avec Claude Code sur le poste.

## Architecture

```text
navigateur ──HTTPS──> [web]  application FastAPI (port 8000)
                        │  API protégée par mot de passe (réseau Docker interne)
                        v
                      [moteur]  opencode serve ──> [web] /ia (relais, ajoute la clé) ──> OpenRouter / Anthropic / OpenAI
                        │
[web] ── publier_squash.mjs ──> Squash TM (seul chemin d'écriture, sur confirmation)
volume « projets » : projets/<code>/01-entrant … 04-livrables, partagé par les deux conteneurs
volume « donnees » : base SQLite (comptes, tâches, audit, paramètres), clé de session, modèles de documents
```

Les dossiers de projets ont exactement la même organisation que dans `qa-factory` : les skills et les scripts fonctionnent sans changement.

## Installation sur le serveur

Prérequis : un serveur Linux avec Docker et Docker Compose, environ 4 processeurs, 16 Go de mémoire, 100 Go de disque ; accès sortant à `openrouter.ai`, au registre npm (`registry.npmjs.org`, OpenCode y télécharge le module du fournisseur au premier usage) et à Squash.

1. Placer côte à côte les deux dépôts :
   ```text
   /opt/qa/qa-factory-saas/
   /opt/qa/squash-tm-mcp/        (le fork, celui de qa-factory)
   ```
2. Configurer :
   ```bash
   cd /opt/qa/qa-factory-saas/saas
   cp .env.exemple .env && chmod 600 .env
   nano .env      # QAF_SECRET, QAF_ADMIN_MOT_DE_PASSE, OPENCODE_SERVER_PASSWORD, OPENROUTER_API_KEY, QAF_MODELE, QAF_CLE_SECRETS
   ```
   Squash ne se règle pas dans `.env` : chaque utilisateur connecte son propre Squash depuis la page **Squash** de l'application (adresse, identifiant et mot de passe ou jeton d'API ; la connexion est testée avant d'être enregistrée, le secret est chiffré). Clé de chiffrement : `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` (sans elle, une clé est créée dans le dossier des données : à sauvegarder avec la base). `QAF_SQUASH_RESEAU_PRIVE=true` seulement si les Squash visés sont sur un réseau interne.
   Pour générer les deux secrets : `python3 -c "import secrets; print(secrets.token_urlsafe(48))"`.
3. Construire et démarrer :
   ```bash
   docker compose up -d --build
   docker compose ps                     # moteur et web « running »
   curl -s http://localhost:8000/sante   # {"application":"ok","moteur":"ok"}
   ```
4. Ouvrir `http://<serveur>:8000`, se connecter avec `QAF_ADMIN_IDENTIFIANT` et le mot de passe provisoire, le changer, puis créer les comptes de l'équipe (menu Utilisateurs).
5. Placer l'application derrière le HTTPS de l'entreprise (reverse proxy) et mettre `QAF_COOKIE_SECURISE=true`.

### Essai sans clé OpenRouter

Avec `QAF_MODELE=simulation/demo`, un faux modèle rejoue l'analyse de référence de SauceDemo. Tout le reste est réel : OpenCode, confirmations, Excel/Word, validation, publication (vers le Squash configuré : utiliser un projet d'essai). Utile pour valider l'installation et former l'équipe avant d'engager des coûts.

### Choisir le modèle (phase 1)

1. Créer une clé OpenRouter dédiée avec un plafond mensuel ; activer dans le compte OpenRouter l'option Zero Data Retention (fournisseurs qui ne conservent pas les données).
2. Pour chaque modèle candidat : `QAF_MODELE=openrouter/<fournisseur>/<modèle>`, `docker compose up -d`, analyser SauceDemo (projet neuf avec son cahier des charges), noter le coût affiché sur la tâche, la durée, et comparer l'analyse à `projets/saucedemo/02-a-valider` (contrôle, techniques, questions).
3. Garder un ou deux modèles ; les modèles légers dégradent nettement l'analyse.

## Exploitation

| Besoin | Commande (dans `saas/`) |
|---|---|
| Journaux | `docker compose logs -f web` ou `moteur` |
| Redémarrer | `docker compose restart` |
| Mettre à jour le code | `git pull` puis `docker compose up -d --build` (tester d'abord sur SauceDemo) |
| Administrateur de secours | `docker compose exec web python3 -m app.admin creer-admin <identifiant> "<Nom>"` |
| Lister les comptes | `docker compose exec web python3 -m app.admin lister` |
| Sauvegarde | voir ci-dessous |

Sauvegarde quotidienne (à planifier avec cron) des volumes `projets` et `donnees` :
```bash
docker run --rm -v qa-factory_projets:/p -v qa-factory_donnees:/d -v /sauvegardes:/s busybox \
  tar czf /s/qa-factory-$(date +%F).tar.gz /p /d
```
Restauration : arrêter (`docker compose down`), extraire l'archive dans les volumes, redémarrer.

Une tâche en cours au moment d'un redémarrage est marquée « Interrompue » : la relancer.

## Développement et tests

```bash
pip install -r saas/requirements.txt pytest
npm install -g opencode-ai@1.19.5
cd saas && SQUASH_MCP_DIR=/chemin/squash-tm-mcp python3 -m pytest -q tests
```

Le test de parcours lance le vrai OpenCode avec le faux modèle (`saas/dev/faux_modele.py`) et un faux Squash (`saas/tests/faux_squash.py`), puis déroule tout le temps A dans l'application : comptes et rôles, création, dépôt, analyse avec confirmation, correction par l'Excel, validation, simulation, publication, absence de doublon, specs, et des contrôles de sécurité (accès sans connexion, sortie du dossier projet, CSRF, droits).

| Fichier | Rôle |
|---|---|
| `app/main.py` | Pages et actions du parcours |
| `app/gabarits/`, `app/statique/` | Écrans, style Synelia (police Nunito hébergée, licence OFL), comportements (`app.js`) |
| `dev/demo.py` | Démonstration locale en une commande |
| `app/moteur.py` | Pilotage d'`opencode serve` (sessions, commandes, confirmations, coût) |
| `app/taches.py` | File des tâches longues (IA, publication, specs) |
| `app/projets.py` | Opérations sur les dossiers de projets via `outils/` |
| `app/securite.py`, `app/db.py` | Comptes, rôles, CSRF ; base SQLite |
| `app/parametres.py`, `app/relais_ia.py` | Paramètres de l'outil (modèles d'IA, clés, modèles de documents) ; relais vers le fournisseur d'IA |
| `publier_squash.mjs` | Publication Squash sans IA (code du MCP squash-tm) |
| `opencode.serveur.json`, `config_moteur.py` | Configuration OpenCode du serveur (surcouche prioritaire sur `opencode.json`) |
| `Dockerfile`, `docker-compose.yml`, `demarrer.sh`, `.env.exemple` | Installation |

## Limites connues de cette version

- Temps B : l'exploration libre ne se fait pas encore dans l'application (avec `qa-factory` sur un poste). Le manuel utilisateur dépend de la qualité du modèle d'IA : relire `points_a_confirmer_manuel.md`. Les tests d'API (fixture `request`) ne sont pas pris en charge par l'exécution des scripts.
- Base SQLite : suffisante pour une équipe ; à remplacer par PostgreSQL si l'outil s'ouvre à plusieurs équipes.
- Comptes locaux uniquement (pas encore de connexion avec les comptes Windows de l'entreprise).
- Une connexion Squash par utilisateur : dans Squash, les créations apparaissent sous le compte de la personne qui a envoyé. Un projet déjà envoyé dans une instance Squash ne peut pas être envoyé dans une autre.
- L'image a été construite et vérifiée sous Docker Desktop le 2026-11-06 (moteur et web, faux modèle) : écriture des scripts par l'assistant, exécution réelle sur SauceDemo, navigateur de l'agent (MCP) avec secrets masqués et domaines limités. Le modèle réel (clé OpenRouter) reste à essayer.
