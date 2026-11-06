# AGENTS.md — Framework d'automatisation QA {{APPLICATION}}

Modèle issu des projets ANSUT, BNI Agora et Orange eFacture. Remplacer les marqueurs `{{…}}` par les valeurs de `projet.json` ; ne rien ajouter qui ne soit pas documenté ou observé.

## 1. Présentation

Le projet construit et maintient un framework End-to-End pour **{{APPLICATION}}** ({{URL}}). Espaces ou modules concernés : {{ESPACES}}.

Rôle des documents :
- `agents/AGENTS.md` (ce fichier) : **comment** développer le framework et les tests ;
- `agents/project-overview.md` : **contexte** (environnements, comptes de test, rôles, limites) ;
- `agents/features/<fonctionnalite>.md` : **quoi** automatiser. Specs générées par QA Factory depuis les cas validés : au statut BROUILLON tant que l'application n'a pas été explorée (libellés, locators et enchaînements à relever), CONFIRMÉE après exploration. Les identifiants `CT0001` y sont ceux de Squash et du cahier de tests.

La spec fonctionnelle est la référence pour décider quoi tester ; l'application observée confirme les interactions mais ne remplace pas la règle métier.

## 2. Stack

Playwright Test, {{LANGAGE}}, Node.js, Allure en complément du rapport Playwright, rapporteur de preuves `utils/evidence-reporter.js`.

Le langage ({{LANGAGE}}) est fixé à la création du dépôt : ne pas en changer, ne pas mélanger les deux. En JavaScript : CommonJS (`require`). En TypeScript : modules ES (`import`), typage simple, exécuté directement par Playwright (pas d'étape de compilation).

Ne pas introduire sans demande explicite : Jest, Cypress, Selenium, Cucumber, autre bibliothèque de test. Le Gherkin des specs est une documentation : il est traduit en tests Playwright, pas exécuté par Cucumber.

## 3. Architecture

```text
config/env.{{EXT}}            URL et comptes de test depuis .env (jamais en dur)
pages/<espace>/*.page.{{EXT}} Page Objects : locators, interactions, navigation
tests/<fonctionnalite>/<fonctionnalite>.spec.{{EXT}}
data/<fonctionnalite>.json   données de test fictives ou autorisées
utils/                   helpers génériques (evidence, unique)
agents/                  AGENTS.md, project-overview.md, features/
docs/test-inventory.md   inventaire de couverture et statuts
```

Ne pas créer sans demande : `fixtures/`, `services/`, `controllers/`, `repositories/`, `factories/`, `flows/`, `managers/`, ni fixture Playwright personnalisée. Organiser par domaine fonctionnel, jamais par type technique (`e2e/`, `unit/`…).

## 4. Séparation des responsabilités

```text
TEST  →  PAGE OBJECT  →  PLAYWRIGHT  →  APPLICATION
```

- **Tests** : scénario, orchestration, **assertions**.
- **Page Objects** : locators, interactions, navigation. **Aucune assertion fonctionnelle.**
- Avant de créer une Page Object : chercher l'existante, la réutiliser ou l'étendre, ne créer que ce qui manque.

## 5. Écriture des tests

- Un test = un scénario de spec. Titre : `[CT0001] <titre du scénario> @<fonctionnalite>` (ajouter `@smoke` si la spec le porte).
- Un `test.step` par STEP de la spec, libellé avec le WHEN / THEN.
- Données dans `data/<fonctionnalite>.json` ; créations avec un suffixe unique (`utils/unique.{{EXT}}`) pour rester rejouable et identifiable.
- Captures d'étape utiles avec `captureStep` (`utils/evidence.{{EXT}}`) ; masquer tout champ sensible.
- Tests indépendants ; préconditions explicites ; cibler les données créées par le test, jamais « la première ligne du tableau ».
- Ne pas affirmer qu'une création, modification ou suppression a eu lieu sans vérifier le résultat observable.

## 6. Locators

Priorité : `data-testid` → `id` → `name` → `getByRole` / `getByLabel` / `getByPlaceholder` / texte stable → CSS stable → XPath en dernier recours.

Jamais : XPath absolu, sélecteur positionnel quand un autre ciblage existe, classe générée, locator inventé ou recopié d'une autre application. Les locators de la spec CONFIRMÉE ont été vérifiés : les réutiliser, et si l'un ne fonctionne plus, réinspecter l'application.

## 7. Synchronisation

Attentes Playwright sur un état observable (`expect(locator).toBeVisible()`, `toHaveURL`, `toHaveText`, réponse réseau précise). `page.waitForTimeout()` interdit sauf nécessité démontrée et commentée.

## 8. Données, secrets, environnements

- Secrets dans `.env` (non versionné) ou variables d'environnement : `BASE_URL`, puis un couple par compte de test, `COMPTE_1_IDENTIFIANT` / `COMPTE_1_MOT_DE_PASSE`, `COMPTE_2_…` (rôles décrits dans `.env.example`). Dans le code : `env.compte(1).identifiant`, `env.compte(1).motDePasse`. `APP_USERNAME` / `APP_PASSWORD` restent acceptés pour le compte 1.
- Jamais de mot de passe, jeton, donnée personnelle ou de paiement réelle dans le code, les specs, les captures ou les rapports.
- Actions autorisées dans l'environnement : {{ACTIONS_AUTORISEES}}. Aucune action destructive, paiement réel ou test intrusif hors de ce périmètre.

## 9. Exécution et rapports

```bash
npm install
npx playwright install chromium
npx playwright test
npx playwright test --grep @<fonctionnalite>
npm run allure:generate && npm run allure:open
```

Exécution depuis QA Factory : l'application lance les tests elle-même, avec les comptes de test du projet, dans un navigateur limité aux domaines de l'application (`QAF_HOTES_AUTORISES`). Avant, elle remet `config/`, `utils/` et `playwright.config.*` à l'identique du gabarit et refuse les scripts qui sortent du navigateur : import autre que `@playwright/test` et les fichiers du dépôt, `process`, `eval`, `fetch` ou fixture `request`, `launchOptions`, adresse hors de l'application, `package.json` / `tsconfig.json` / `.env` / `node_modules` dans `pages/`, `tests/`, `data/`.

Après chaque modification : exécuter les tests concernés, analyser les échecs, distinguer défaut du test / défaut applicatif / environnement. Mettre à jour `docs/test-inventory.md` : ID, scénario, test, statut (PASS, FAIL, BLOCKED, NEEDS_DISCOVERY, NOT_RUN), preuve (`evidence/<run>/…`), commentaire.

## 10. Méthode de l'agent

1. Lire ce fichier, `project-overview.md`, puis la spec de la fonctionnalité.
2. Vérifier son statut. **CONFIRMÉE** : ses locators ont été vérifiés. **BROUILLON** (cas normal à la première génération depuis QA Factory) : explorer d'abord l'application avec le navigateur disponible (parcours du scénario, libellés, locators réels), puis écrire le test ; ce qui n'a pas pu être observé est marqué `// À VÉRIFIER : non observé`. Sans navigateur ni accès à l'application, ne pas écrire de test : demander une exploration. Ne pas modifier la spec elle-même.
3. Identifier scénarios, données, interactions, assertions, locators.
4. Réutiliser Page Objects, données, utilitaires ; créer uniquement ce qui manque.
5. Exécuter, corriger la cause réelle des échecs (3 tentatives max sur un défaut de test).
6. Rendre compte : fichiers créés ou modifiés, tests exécutés, résultats réels, limites.

## 11. Règles impératives

1. Ne rien inventer : fonctionnalité, rôle, statut, message, URL, locator.
2. Assertions dans les tests, interactions dans les Page Objects.
3. Pas de fixture personnalisée, pas d'attente fixe sans justification.
4. Ne jamais affaiblir une assertion ni désactiver un test pour obtenir du vert.
5. Aucun secret versionné ; aucune action hors du périmètre autorisé.
6. Rapporter honnêtement PASS, FAIL, BLOCKED, NOT_RUN.
7. Après une correction, rejouer le test et la régression pertinente.
