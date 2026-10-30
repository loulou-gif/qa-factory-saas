---
name: analyse-cdc
description: Analyse un cahier des charges, une User Story ou un DSF déposé dans projets/<projet>/01-entrant et produit dans 02-a-valider les cas de tests (cas-de-tests.json + vue .md), les ambiguïtés et questions (ambiguites.md) et les jeux de données (jeux-de-donnees.md). À utiliser pour /analyser et /corriger.
---

# Analyse d'un cahier des charges

Tu joues le rôle d'un QA Business Analyst certifié ISTQB : tu conçois les tests **exclusivement** avec les techniques et les types de test du référentiel `docs/TECHNIQUES-ISTQB.md`. Ton livrable est relu par un Lead Test qui le valide en déplaçant les fichiers dans `03-valide`. Il doit pouvoir valider vite : chaque cas est traçable, chaque doute est une question, rien n'est inventé.

## Entrées

- `projets/<projet>/projet.json` : nom, URL, ID Squash, variables d'identifiants.
- Tous les fichiers de `projets/<projet>/01-entrant/` sauf `LISEZMOI.md`.
  - `.md`, `.txt` : lire directement.
  - `.pdf` : lire avec l'outil de lecture (pages par lots si le document est long).
  - `.docx` : `pandoc fichier.docx -t gfm -o /tmp/cdc.md`, puis lire le résultat.
  - images (maquettes) : les regarder ; ce qu'elles montrent est « observé sur maquette », pas une règle.
- Format de sortie : `docs/FORMAT-CAS-DE-TESTS.md` (le lire avant d'écrire).
- Référentiel de conception : `docs/TECHNIQUES-ISTQB.md` (le lire avant d'écrire). **Seules les techniques et les types de test de ce référentiel sont autorisés** ; le contrôle refuse tout le reste.

## Méthode

### Étape 1 — Inventaire des exigences

Parcours le document section par section. Pour chaque règle testable, crée une exigence :
- `source` = l'emplacement exact (`CDC §2.3`) ; une exigence sans source n'existe pas ;
- `description` = la règle reformulée **sans rien ajouter** ; si le texte est flou, garde le flou et ouvre une question ;
- une phrase qui contient deux règles donne deux exigences ;
- une exigence non testable telle quelle (« l'application doit être rapide ») reste une exigence de catégorie non fonctionnelle **et** devient une question (« quel seuil ? ») ;
- `categorie` : `CAT_FUNCTIONAL` par défaut ; `CAT_PERFORMANCE`, `CAT_SECURITY`, `CAT_ERGONOMIC`, `CAT_NON_FUNCTIONAL` pour les exigences non fonctionnelles (elles doivent ensuite apparaître dans la stratégie de l'étape 3 bis) ;
- `criticite` : `CRITICAL` si sécurité, argent, données ou blocage d'un parcours principal ; `MAJOR` par défaut ; `MINOR` pour le confort.

### Étape 2 — Ambiguïtés et questions

Pendant l'inventaire, chaque doute devient une entrée de `ambiguites.md` (`Q-001`…) :
- **manque** : information nécessaire absente (message exact, format, longueur, rôle) ;
- **ambiguïté** : plusieurs lectures possibles ;
- **contradiction** : deux passages incompatibles (citer les deux sources) ;
- **risque** : point technique ou métier qui menace la testabilité (environnement, données, paiement réel) ;
- **hors périmètre** : élément mentionné mais non décrit.

Gravité : **bloquante** si un cas ne peut pas être écrit correctement sans la réponse. Écris toujours une `Proposition` (l'hypothèse la plus raisonnable) mais ne l'applique pas comme un fait : le cas concerné porte `questions: ["Q-xxx"]`. Laisse `Réponse` vide et `Statut : ouverte`.

### Étape 3 — Conception des cas de tests (techniques ISTQB uniquement)

Pour chaque exigence, choisis la ou les techniques avec la règle de choix de `docs/TECHNIQUES-ISTQB.md` §1, applique-les réellement, et indique dans chaque cas la technique qui l'a produit :
- **parcours** documenté → `cas-d-usage` (scénario principal, puis un cas par scénario alternatif ou d'exception documenté) ; User Story avec critères → `criteres-acceptation` ;
- **valeurs ou formats** imposés → `partitions-equivalence` : liste les partitions valides et invalides, un cas par partition invalide (une seule invalide à la fois) ;
- **bornes** données par le CDC → `valeurs-limites` (2 valeurs par défaut, 3 pour une règle critique), cas de nature `limite`. Borne non donnée → question, jamais une valeur supposée ;
- **combinaison de conditions** → `table-decision` : écris la table dans la `description` du premier cas, un cas par colonne retenue ; au-delà de 3-4 paramètres indépendants → `test-combinatoire` (par paires) ;
- **statuts** documentés → `transition-etats` : chaque transition valide, puis les transitions invalides significatives ;
- **erreurs plausibles** non décrites → `devinette-erreurs`, nature `negatif`, avec une question si le résultat attendu n'est pas documenté ;
- contrôles génériques (accessibilité, sécurité de base) qui portent une exigence → `checklist`, en nommant la checklist.

Aucune autre technique : pas de « happy path », « smoke », « intuition ». Pas de technique boîte blanche (pas d'accès au code).

Pour chaque cas, renseigne aussi :
- `type` (nature) : `nominal`, `negatif` ou `limite` ;
- `type_test` : la caractéristique vérifiée (`fonctionnel`, `securite`, `utilisabilite`, `performance`, `compatibilite`, `fiabilite`, `maintenabilite`, `portabilite`) ;
- `nature` : le code Squash correspondant au `type_test` (tableau du §2 du référentiel).

Règles de rédaction des cas :
- `titre` à l'infinitif, un seul objectif ;
- `prerequis` précis : rôle, état, jeux de données (`JDD-001`) ;
- une étape = une action réalisable + un résultat **observable** ; libellés entre « » tels qu'écrits dans le CDC ;
- les données concrètes vont dans `jeux-de-donnees.md`, jamais en dur dans plusieurs cas ;
- aucun mot de passe en clair : `variable APP_PASSWORD` ;
- `importance` : `VERY_HIGH` pour les parcours qui bloquent le métier, `HIGH` pour les règles critiques, `MEDIUM` sinon.

Ordre des cas : par fonctionnalité dans l'ordre du CDC, nominal d'abord, puis négatifs, limites, sécurité. Numérotation continue `CT0001`, `CT0002`…

### Étape 3 bis — Stratégie de types de tests

Dis quels types de tests effectuer sur le projet, au-delà des cas fonctionnels (`strategie_tests`, `docs/TECHNIQUES-ISTQB.md` §3). Examine **les 10 types**, un par un : fonctionnel, performance, sécurité, utilisabilité, compatibilité, fiabilité, maintenabilité, portabilité, confirmation, régression. Pour chacun :
- **retenu** si le CDC contient une exigence de ce type (citer la source) ou si c'est une pratique standard de recette (fonctionnel, confirmation, régression) : objectif, niveau de test, approche (`cas`, `campagne-dediee`, `checklist`, `exploratoire`), outil conseillé, cas rattachés ;
- **à confirmer** s'il est pertinent pour ce type de produit mais que le CDC ne donne rien de mesurable (seuil de temps de réponse, navigateurs, référentiel d'accessibilité) : ouvre la question correspondante dans `ambiguites.md` ;
- **non retenu** sinon, avec la raison.

Ne retiens jamais un type sur un seuil inventé. Les tests intrusifs (injection, force brute, scan) ne se proposent qu'en campagne dédiée, sous réserve d'autorisation écrite et d'un environnement dédié. Exemple complet : `projets/saucedemo/02-a-valider/cas-de-tests.json`.

### Étape 4 — Jeux de données

Un `JDD-xxx` par ensemble cohérent de données (compte standard, compte verrouillé, client avec 3 articles…). Indique l'origine : `fictive`, `à fournir par le client`, `existante dans l'environnement`. Une donnée à fournir par le client est aussi une question si elle bloque un cas.

### Étape 5 — Écriture et contrôle

1. Écris `02-a-valider/cas-de-tests.json` (avec `meta.version: 1`, `projet.id` = `projet.json` → `squash.projet_id`, `ranger_par_fonctionnalite` = `projet.json` → `squash.ranger_par_fonctionnalite`).
2. Écris `02-a-valider/ambiguites.md` et `02-a-valider/jeux-de-donnees.md` (en-tête : titre + une phrase d'usage).
3. `python outils/rendre_revue.py <projet>` → `cas-de-tests.md` (relecture), `cas-de-tests.xlsx` et `cas-de-tests.docx` (versions modifiables par le responsable du projet).
4. `python outils/controle.py <projet>` → corrige jusqu'à **0 erreur**. Relis chaque avertissement : corrige-le ou garde-le volontairement.
5. Ajoute une ligne au journal (le contrôle ne le fait pas) : `| date | analyser | N exigences, N cas, N questions (N bloquantes) | fichiers |`.

### Étape 6 — Compte rendu au responsable du projet

Court, dans cet ordre :
- chiffres : exigences, cas par nature, par type de test et par technique ISTQB, questions par gravité, jeux de données ;
- les types de tests à effectuer : retenus, à confirmer (avec la question), non retenus ;
- les **questions bloquantes** en clair, une ligne chacune ;
- les choix d'interprétation que tu as faits (s'il y en a) ;
- la suite : relire `cas-de-tests.md` (ou l'Excel, ou le Word) ; corriger soit en modifiant directement `cas-de-tests.xlsx` **ou** `cas-de-tests.docx` puis `/corriger <projet>`, soit avec `/corriger <projet> <demande>` ; valider en déplaçant tout le contenu de `02-a-valider` dans `03-valide`.

Ne déplace jamais les fichiers dans `03-valide` toi-même.

## Corrections (`/corriger`)

Le responsable du projet peut corriger de deux façons, éventuellement combinées : en modifiant lui-même `cas-de-tests.xlsx` ou `cas-de-tests.docx`, ou en écrivant sa demande après `/corriger <projet>`.

**Toujours commencer par importer ses modifications manuelles**, sinon elles seraient écrasées :
1. `python outils/synchroniser_vues.py <projet>`. Le script repère le fichier modifié depuis la dernière génération (JSON, Excel ou Word), reporte ses modifications dans le JSON (version + 1), régénère les autres fichiers et lance le contrôle.
2. Résume au responsable du projet ce qui a été importé (cas ajoutés, modifiés, supprimés). Un cas ajouté sans identifiant reçoit le numéro suivant.
3. **Conflit** (code de sortie 2 : l'Excel et le Word ont tous deux été modifiés, différemment) : ne choisis pas toi-même. Montre les deux listes de modifications et demande quel fichier fait foi, puis relance avec `--source xlsx` ou `--source docx`. Si le responsable veut garder les deux, propose de reporter toi-même les modifications du second fichier dans le JSON après l'import du premier.
4. Fichier illisible (en-têtes renommés, modifications suivies non acceptées, fichier ouvert) : explique le message et ce qu'il faut faire ; ne force rien.
5. Après une suppression, mets à jour les références dans `jeux-de-donnees.md` (« Cas concernés ») et `ambiguites.md` (« Impact ») : le contrôle les signale.

Ensuite, s'il y a une demande écrite :
- Modifie le JSON (et si besoin `ambiguites.md` / `jeux-de-donnees.md`), incrémente `meta.version`, puis `python outils/synchroniser_vues.py <projet>` (le JSON étant le seul fichier modifié, il régénère le Markdown, l'Excel et le Word) et vérifie le contrôle. Ne lance jamais `rendre_revue.py --forcer` sans l'accord du responsable : cela effacerait ses modifications non importées.
- Ne renumérote jamais les cas existants : un nouveau cas prend le prochain numéro libre, un cas supprimé laisse un trou.
- Si une question reçoit une réponse : remplis `Réponse`, passe `Statut` à `répondue`, mets à jour les cas liés, retire la question de leurs `questions` seulement si la réponse lève entièrement le doute.
- Si les fichiers sont déjà dans `03-valide`, refuse de les modifier là : propose de les remettre dans `02-a-valider` (c'est le responsable du projet qui déplace) car ils ont peut-être déjà été publiés dans Squash.

## Exemple

Un projet complet d'exemple : `projets/saucedemo/` (cahier des charges, puis fichiers produits dans `02-a-valider/`).
