# Tests automatisés Playwright : {{APPLICATION}}

Dépôt généré par QA Factory ({{LANGAGE}}). Chaque test porte la référence de son cas de test dans
son titre (`[CT0001] …`) ; la correspondance est tenue dans `docs/test-inventory.md`.

## Lancer les tests sur un poste

Prérequis : Node.js 20 ou plus.

```bash
npm install
npx playwright install chromium
cp .env.example .env      # puis renseigner BASE_URL et les comptes de test
npx playwright test
npx playwright show-report
```

Le fichier `.env` contient les mots de passe des comptes de test : il ne se versionne jamais
(il est dans `.gitignore`).

## Organisation

| Dossier | Contenu |
|---|---|
| `tests/` | un fichier `.spec.{{EXT}}` par fonctionnalité, un test par cas |
| `pages/` | Page Objects : locators et actions de chaque écran |
| `data/` | jeux de données de test |
| `config/`, `utils/` | configuration et outils communs, fournis par le gabarit |
| `agents/` | consignes et specs utilisées pour écrire les tests |
| `docs/test-inventory.md` | inventaire : cas, test, fichier, dernier résultat |
