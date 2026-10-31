# QA Factory SaaS (version serveur)

Application web interne : les testeurs utilisent QA Factory depuis un navigateur, sans rien installer. Elle pilote le même moteur que `qa-factory` (skills, règles ISTQB, scripts, MCP Squash), installé une seule fois sur un serveur.

État : **phases 1 et 2** de la feuille de route (moteur sur serveur, temps A complet). Le temps B (exploration, recette, cahier de tests, manuel) arrive en phase 5 ; d'ici là, il se fait avec `qa-factory` sur un poste.

## Ce que fait l'application

| Étape | Qui | Dans la page du projet |
|---|---|---|
| Créer le projet | Responsable, administrateur | Code, nom, adresse du site (facultative), ID Squash (facultatif), responsable |
| Déposer le cahier des charges | Tous | Formats : pdf, docx, doc, odt, md, txt, xlsx, png, jpg |
| Analyser | Tous | L'IA produit cas (techniques ISTQB), stratégie des 10 types de tests, questions, jeux de données ; suivi en direct ; les actions sensibles de l'agent demandent une confirmation dans la page |
| Relire | Tous | En ligne, ou Excel / Word téléchargés |
| Corriger | Tous | Renvoyer l'Excel ou le Word modifié (pris en compte immédiatement, sans IA), ou écrire une demande à l'IA ; conflit Excel/Word détecté et arbitré par un bouton |
| Valider | Responsable du projet, administrateur | Bouton ; refusé si le contrôle signale des erreurs ou si un fichier modifié n'a pas été renvoyé |
| Publier dans Squash | Responsable du projet, administrateur | Simulation, puis bouton de confirmation ; sans IA, avec le code du MCP squash-tm ; jamais de modification ni de suppression dans Squash, jamais de doublon |
| Specs d'automatisation | Tous | Specs BROUILLON par fonctionnalité |

Garde-fous propres à la version serveur :
- l'agent IA n'a **aucun** droit d'écriture dans Squash, ni d'accès web, ni d'accès hors du dépôt ; la publication passe uniquement par le bouton du responsable ;
- toute commande système non prévue demande une confirmation dans la page, avec le nom de la personne qui l'a accordée ;
- une seule tâche à la fois par projet ; chaque tâche affiche son coût OpenRouter (jetons et dollars) ;
- comptes nominatifs (administrateur, responsable de projet, testeur), mots de passe hachés, mot de passe provisoire à changer à la première connexion, protection CSRF, journal d'audit.

## Architecture

```text
navigateur ──HTTPS──> [web]  application FastAPI (port 8000)
                        │  API protégée par mot de passe (réseau Docker interne)
                        v
                      [moteur]  opencode serve ──> OpenRouter (modèle imposé, clé côté serveur)
                        │                      └─> MCP squash-tm (lecture seule pour l'agent)
volume « projets » : projets/<code>/01-entrant … 04-livrables, partagé par les deux conteneurs
volume « donnees » : base SQLite (comptes, tâches, audit) et clé de session
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
   nano .env      # QAF_SECRET, QAF_ADMIN_MOT_DE_PASSE, OPENCODE_SERVER_PASSWORD, OPENROUTER_API_KEY, QAF_MODELE, Squash
   ```
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
| `app/main.py` | Pages et actions |
| `app/moteur.py` | Pilotage d'`opencode serve` (sessions, commandes, confirmations, coût) |
| `app/taches.py` | File des tâches longues (IA, publication, specs) |
| `app/projets.py` | Opérations sur les dossiers de projets via `outils/` |
| `app/securite.py`, `app/db.py` | Comptes, rôles, CSRF ; base SQLite |
| `publier_squash.mjs` | Publication Squash sans IA (code du MCP squash-tm) |
| `opencode.serveur.json`, `config_moteur.py` | Configuration OpenCode du serveur (surcouche prioritaire sur `opencode.json`) |
| `Dockerfile`, `docker-compose.yml`, `demarrer.sh`, `.env.exemple` | Installation |

## Limites connues de cette version

- Temps B non disponible (phase 5) : le navigateur Playwright du moteur est désactivé.
- Base SQLite : suffisante pour une équipe ; à remplacer par PostgreSQL si l'outil s'ouvre à plusieurs équipes.
- Comptes locaux uniquement (pas encore de connexion avec les comptes Windows de l'entreprise).
- Un compte Squash de service pour tout l'outil : dans Squash, les créations apparaissent sous ce compte (l'application garde, elle, le nom de la personne qui a publié).
- L'image Docker n'a pas pu être construite dans l'environnement de développement (registre Docker inaccessible) : la première construction se fait sur le serveur ; chaque commande de l'image a été vérifiée séparément.
