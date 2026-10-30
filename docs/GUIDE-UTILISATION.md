# Guide d'utilisation des documents

Ce guide explique, document par document, **à quoi il sert, qui l'écrit, quand, et ce que le testeur en fait**. Il vaut pour Claude Code comme pour OpenCode. Pour l'installation, voir `README.md` (et `docs/OPENCODE.md` pour OpenCode).

Trois règles à garder en tête :
1. **Un seul fichier fait foi** : `cas-de-tests.json`. Squash, le cahier Excel, les specs et la matrice en sont générés. Pour relire et corriger confortablement, les cas existent aussi en **Excel et en Word modifiables** : on modifie l'un des deux, puis `/corriger` reporte les modifications dans le JSON et met à jour tout le reste (section 3).
2. **Valider, c'est déplacer.** Le responsable du projet valide l'analyse en déplaçant tout le contenu de `02-a-valider/` vers `03-valide/`. L'agent ne le fait jamais.
3. **Deux temps.** Temps A : le cahier des charges suffit. Temps B : il faut le lien de la plateforme, l'environnement et les comptes de test. Le cahier de tests et le manuel ne sont produits qu'en temps B.

## 1. Vue d'ensemble d'un projet

```text
projets/<projet>/
├── projet.json              fiche du projet (à compléter par le responsable)
├── journal.md               historique des étapes (écrit par l'agent)
├── 01-entrant/              documents du client (déposés par le responsable)
├── 02-a-valider/            analyse proposée par l'agent (relue par le responsable)
│   ├── cas-de-tests.json        source : exigences, cas, stratégie de types de tests
│   ├── cas-de-tests.md          vue de relecture (générée, lecture seule)
│   ├── cas-de-tests.xlsx        cas de tests en Excel (généré, MODIFIABLE)
│   ├── cas-de-tests.docx        cas de tests en Word (généré, MODIFIABLE)
│   ├── ambiguites.md            questions au client
│   ├── jeux-de-donnees.md       données de test nécessaires
│   └── matrice-tracabilite.md   exigences → cas (générée)
├── 03-valide/               même contenu, une fois validé (déplacé par le responsable)
└── 04-livrables/
    ├── squash/correspondance.json   lien identifiants ↔ Squash (généré, à committer)
    ├── specs/*.md                   specs d'automatisation (BROUILLON puis CONFIRMÉE)
    ├── exploration/                 découvertes, écarts, captures (temps B)
    ├── cahier/                      cahier de tests Excel + points à confirmer (temps B)
    └── manuel/                      manuel utilisateur Word/PDF + points à confirmer (temps B)
```

## 2. Le parcours, étape par étape

| Étape | Commande | Le testeur fait | Documents produits |
|---|---|---|---|
| 1 | `/nouveau-projet <nom> <url> <id Squash>` | Complète `projet.json` (client, responsable, environnement, auteur du cahier) | `projet.json`, dossiers |
| 2 | — | Dépose CDC, US, DSF, maquettes dans `01-entrant/` | — |
| 3 | `/analyser <projet>` | Attend le compte rendu | les fichiers de `02-a-valider/` (dont l'Excel et le Word des cas) |
| 4 | `/corriger <projet>` ou `/corriger <projet> <demande>` | Relit (section 3), corrige dans l'Excel ou le Word, ou écrit sa demande ; fait répondre le client aux questions | nouvelle version ; JSON, Markdown, Excel et Word à jour |
| 5 | — | **Valide** : déplace tout le contenu de `02-a-valider/` dans `03-valide/` | — |
| 6 | `/publier <projet>` | Lit la simulation, donne son accord explicite | exigences et cas dans Squash, `correspondance.json` |
| 7 | `/specs <projet>` | Rien (les specs restent BROUILLON) | `04-livrables/specs/` |
| 8 | `/explorer <projet>` | Fournit les comptes (variables d'environnement), arbitre les écarts | `04-livrables/exploration/`, specs CONFIRMÉES |
| 9 | `/recette <projet>` | Relit les trois livrables | tests Playwright, cahier Excel, manuel Word |
| — | `/statut [projet]` | Suit l'avancement | — |

## 3. Les documents de l'analyse (`02-a-valider/` puis `03-valide/`)

### Les cas de tests en quatre formats

| Fichier | Pour quoi faire | Modifiable ? |
|---|---|---|
| `cas-de-tests.xlsx` | Relire et corriger dans Excel : filtres, tri, listes déroulantes | **Oui** |
| `cas-de-tests.docx` | Relire et corriger dans Word : une fiche par cas, facile à imprimer ou commenter | **Oui** |
| `cas-de-tests.md` | Relire dans un éditeur de texte ou sur GitHub | Non (régénéré) |
| `cas-de-tests.json` | La source, lue par Squash et les outils | Réservé aux spécialistes |

Les quatre contiennent la même chose : la stratégie de types de tests, les exigences et les cas avec leurs étapes.

### Corriger dans l'Excel ou le Word

1. Ouvrir **l'un des deux** (`cas-de-tests.xlsx` ou `cas-de-tests.docx`) dans `02-a-valider/`.
2. Modifier, enregistrer, **fermer** le fichier.
3. Dans l'agent : `/corriger <projet>`. Il repère seul le fichier modifié, reporte les changements dans le JSON (la version augmente de 1), régénère les trois autres et lance le contrôle. Il résume ce qu'il a importé : cas ajoutés, modifiés, supprimés.

Dans l'Excel (la feuille « Lisez-moi » rappelle ces règles) :
- feuille « Cas de tests » : une ligne par étape ; les informations du cas (titre, exigences, nature, technique…) sont sur la **première ligne** du cas ;
- ajouter une étape : insérer une ligne sous le cas et remplir seulement Action et Résultat attendu ;
- ajouter un cas : une nouvelle ligne avec au moins un titre, **ID laissé vide** (l'agent donne le numéro suivant) ;
- supprimer un cas : supprimer toutes ses lignes ;
- Nature, Type de test, Technique ISTQB, Importance : listes déroulantes ;
- feuilles « Exigences » et « Stratégie » : une ligne par élément.

Dans le Word :
- chaque cas = un titre « CT0001 — Titre », une fiche (tableau Champ / Valeur) et un tableau d'étapes ;
- ajouter un cas : copier un bloc complet et remplacer le numéro par `CTxxxx` ;
- ajouter une étape : ajouter une ligne au tableau des étapes ;
- ne pas renommer les titres de colonnes ni la première colonne des fiches ;
- accepter les modifications suivies avant `/corriger`.

Ce qu'il faut éviter :
- **modifier l'Excel et le Word en même temps.** L'agent le détecte, n'écrit rien et vous demande lequel garder : les modifications de l'autre seraient perdues ;
- modifier l'Excel ou le Word dans `03-valide/` : ce qui est validé ne se modifie plus (le contrôle le signale). Remettre d'abord les fichiers dans `02-a-valider/` ;
- laisser le fichier ouvert pendant `/corriger` : l'agent ne peut pas le régénérer.

On peut aussi combiner : modifier l'Excel puis écrire `/corriger <projet> ajoute un cas limite sur le code postal`. L'agent importe d'abord l'Excel, puis applique la demande.

### `cas-de-tests.md` — la vue de relecture

Version texte des mêmes contenus. Elle est générée depuis le JSON ; ne pas la modifier (le contrôle le détecte grâce à l'empreinte en première ligne).

Ordre de lecture conseillé :
1. **Synthèse** : nombre d'exigences et de cas, répartition par nature (nominal, négatif, limite), par type de test et par technique ISTQB. Un projet avec 0 cas négatif ou une seule technique mérite une question à l'agent.
2. **Stratégie de types de tests** : les 10 types ISTQB (fonctionnel, performance, sécurité, utilisabilité, compatibilité, fiabilité, maintenabilité, portabilité, confirmation, régression), chacun **retenu**, **à confirmer** ou **non retenu**, avec la justification, le niveau de test, l'approche et l'outil conseillé (Gatling pour la performance, par exemple). C'est la base du plan de test et de la discussion avec le client sur les tests non fonctionnels.
3. **Par fonctionnalité** : les exigences (avec leur source dans le CDC), puis chaque cas avec sa nature, son type de test, **sa technique ISTQB et sa référence au syllabus**, ses prérequis, ses jeux de données, ses questions liées et ses étapes (action → résultat attendu).

Ce qu'il faut vérifier :
- chaque exigence cite un passage réel du CDC ;
- la technique est cohérente avec l'exigence (bornes → valeurs limites ; conditions combinées → table de décision ; statuts → transitions d'états) ;
- chaque résultat attendu est observable (un message, une page, une valeur), jamais « fonctionne correctement » ;
- les cas marqués « suspendu à une question bloquante » ne seront justes qu'après la réponse du client.

Pour corriger : directement dans l'Excel ou le Word (voir plus haut), ou par une demande écrite : `/corriger <projet> ajouter un cas limite sur la longueur du code postal`, `/corriger <projet> CT0012 : le tri par défaut est par prix`.

### `cas-de-tests.json` — la source

Lu par les outils et par Squash, rarement ouvert par le testeur. Format : `docs/FORMAT-CAS-DE-TESTS.md`. Les techniques et types de test autorisés : `docs/TECHNIQUES-ISTQB.md`. Un spécialiste peut le modifier directement, puis lancer `/corriger <projet>` (ou `python outils/synchroniser_vues.py <projet>`) pour mettre à jour l'Excel, le Word et le Markdown.

### `ambiguites.md` — les questions au client

Chaque manque, ambiguïté, contradiction ou risque du CDC devient une question `Q-001`, avec sa gravité :
- **bloquante** : des cas ne peuvent pas être finalisés sans la réponse ;
- **importante** : la réponse change des cas ou la stratégie (seuils de performance, navigateurs) ;
- **mineure** : précision utile.

Comment l'utiliser :
1. Envoyer les questions au client (ou au métier), en commençant par les bloquantes. Chaque question porte une `Proposition` : l'hypothèse que l'agent recommande si le client n'a pas d'avis.
2. Reporter la réponse dans le champ `Réponse` et passer le `Statut` à `répondue`, à la main ou avec `/corriger <projet> réponse à Q-004 : 2 secondes par page pour 100 utilisateurs`.
3. L'agent met à jour les cas liés (et la stratégie : un type « à confirmer » peut devenir « retenu »).

Les questions qui concernent un type de test (performance, compatibilité, accessibilité) apparaissent dans la colonne « Questions » de la stratégie.

### `jeux-de-donnees.md` — les données de test

Un jeu `JDD-001` par ensemble cohérent de données (compte standard, compte verrouillé, panier de 3 articles), avec les cas qui l'utilisent, son origine (fictive, à fournir par le client, existante dans l'environnement) et sa sensibilité. Les mots de passe n'y figurent jamais : seulement le nom de la variable d'environnement (`APP_PASSWORD`).

Comment l'utiliser : demander au client les jeux « à fournir », préparer les autres dans l'environnement de recette avant l'exécution. Les jeux deviennent les jeux de données des cas dans Squash et alimentent la section DATA des specs.

### `matrice-tracabilite.md` — exigences → cas

Générée par le contrôle. Pour chaque exigence : cas nominaux, cas négatifs ou limites, types de test, techniques utilisées, questions ouvertes. Une ligne « **aucun** » signale une exigence non couverte. Utile pour un comité ou pour justifier la couverture auprès du client.

## 4. Les livrables (`04-livrables/`)

### `squash/correspondance.json`

Écrit par la publication : il relie chaque `EX-xxx` et `CT0001` à son identifiant dans Squash. C'est lui qui évite les doublons quand on republie après de nouveaux cas. **À committer après chaque publication et à récupérer (`git pull`) avant de publier.** Ne jamais le modifier ni le supprimer.

### `specs/<fonctionnalite>.md` — specs d'automatisation

Une par fonctionnalité, au format des projets ANSUT et Orange eFacture (SCENARIO, STEP, WHEN/THEN, INTERACT, ASSERT, LOCATOR_RULES). Chaque scénario garde l'identifiant du cas (`CT0001`), son type de test et sa technique.

- `STATUT : BROUILLON` (temps A) : écrite depuis les cas validés, sans locators. Ne pas automatiser.
- `STATUT : CONFIRMÉE` (après `/explorer`) : INTERACT, ASSERT et locators vérifiés sur l'application réelle. Prête pour `/generer-tests`.

Les cas de performance, fiabilité, maintenabilité et portabilité n'ont pas de spec Playwright : ils relèvent de la campagne dédiée prévue dans la stratégie.

### `exploration/`

- `decouvertes.md` : ce que l'agent a observé dans l'application (écrans, routes, libellés, messages), avec la légende **[Observé]**, **[Bundle]**, **[À confirmer]**.
- `ecarts.md` : différences entre les cas validés et l'application (libellé, enchaînement, message, règle). **Le responsable du projet décide** pour chaque écart : corriger le cas (via `02-a-valider` et une nouvelle validation) ou ouvrir une anomalie. Une différence de règle est une anomalie probable, jamais corrigée en silence.
- `captures/` : les captures d'écran qui servent au manuel.

### `cahier/` (temps B)

- `Cahier_de_tests_<projet>_<version>.xlsx` : le cahier au modèle Synelia/BNI, généré depuis le JSON validé. Les colonnes RÉSULTAT, STATUT et COMMENTAIRE sont vides : elles se remplissent pendant l'exécution. La feuille « Traçabilité » donne pour chaque cas : exigences, nature, type de test, technique ISTQB, spec et test automatisé.
- `points_a_confirmer.md` : métadonnées « À renseigner », cas liés à des questions ouvertes.

Version « recette client » (parcours nominaux uniquement) : `/cahier <projet> nominaux`.

### `manuel/` (temps B)

- `Manuel_utilisateur_<Projet>_vX.Y.docx` et son PDF : rédigés depuis l'application réellement observée et les captures, selon `docs/regles-livrables.md`.
- `points_a_confirmer_manuel.md` : procédures non vérifiées, captures manquantes, écarts.
- `generation/contenu_manuel.py` : le contenu source du manuel (pour le régénérer après une correction).

## 5. Les fichiers du projet

### `projet.json`

| Champ | À remplir par | Utilité |
|---|---|---|
| `nom`, `client`, `responsable` | Responsable | Identité ; le responsable est celui qui valide |
| `application.url`, `environnement` | Responsable | Obligatoires pour le temps B (exploration, cahier) |
| `application.actions_autorisees` | Responsable | Ce que l'agent a le droit de faire dans l'application (par défaut : lecture seule) |
| `application.variables_identifiants` | Responsable | Noms des variables d'environnement des comptes de test (jamais les valeurs) |
| `squash.projet_id` | Responsable | ID du projet Squash (créé à la main dans Squash) ; sans lui, pas de publication |
| `cahier.*` | Responsable | Titre, version, auteur, contact du cahier Excel |
| `automatisation.depot` | Agent ou responsable | Chemin du dépôt Playwright du projet |

### `journal.md`

Une ligne par étape (date, commande, résultat, fichiers). C'est l'historique à consulter pour savoir ce qui a été fait, notamment quand plusieurs testeurs travaillent sur le projet. Avec Git, chaque validation devient aussi un commit traçable.

## 6. Les documents de référence (`docs/`)

| Document | Pour qui | Contenu |
|---|---|---|
| `GUIDE-UTILISATION.md` | Toute l'équipe | Ce guide |
| `TECHNIQUES-ISTQB.md` | Testeurs et agent | Les seules techniques de conception et types de test autorisés, avec leurs références au syllabus, la règle de choix et ce que le contrôle vérifie |
| `FORMAT-CAS-DE-TESTS.md` | Spécialistes et agent | Format exact des fichiers d'analyse et liste des contrôles |
| `regles-livrables.md` | Testeurs et agent | Règles de rédaction du manuel et du cahier |
| `OPENCODE.md` | Équipe sous OpenCode | Installation et différences avec Claude Code |

Les fichiers `AGENTS.md`, `CLAUDE.md`, `.claude/` et `.opencode/` sont les consignes de l'agent : à ne modifier que pour faire évoluer la méthode de toute l'équipe (et, pour une commande, lancer ensuite `python outils/synchroniser_opencode.py`).

## 7. Les outils en ligne de commande

Utilisables sans agent, depuis le dossier `qa-factory` :

| Commande | Quand |
|---|---|
| `python outils/controle.py <projet> [--dossier 03-valide]` | Après toute modification : 0 erreur exigé, avertissements à lire |
| `python outils/synchroniser_vues.py <projet>` | Après une modification de l'Excel, du Word ou du JSON (c'est ce que fait `/corriger`) |
| `python outils/rendre_revue.py <projet>` | Régénérer les vues depuis le JSON (refuse si l'Excel ou le Word contient des modifications non importées) |
| `python outils/statut.py [projet]` | Pour savoir où en est un projet |
| `python outils/build_cahier.py <projet> [--nominaux]` | Régénérer le cahier (temps B) |
| `python outils/generer_specs.py <projet>` | Régénérer les specs BROUILLON |
| `python outils/verifier_installation.py` | Vérifier un poste |

## 8. Questions fréquentes

**L'agent a mis une technique que je ne connais pas.** Toutes les techniques autorisées sont dans `docs/TECHNIQUES-ISTQB.md`, avec leur référence (CTFL v4.0, CTFL v3.1, CTAL-TA). Une technique hors liste est refusée par le contrôle.

**Pourquoi le test de performance est « à confirmer » et non « retenu » ?** Parce que le CDC ne donne pas de seuil mesurable. L'agent ne retient jamais un type de test sur un seuil inventé : il ouvre une question. Dès que le client répond, `/corriger` passe le type à « retenu » et décrit la campagne.

**Puis-je modifier un cas directement dans Squash ou dans le cahier de tests Excel (`04-livrables/cahier`) ?** Non : la modification serait perdue à la prochaine génération et casserait la traçabilité. Seuls `cas-de-tests.xlsx` et `cas-de-tests.docx` de `02-a-valider` sont faits pour être modifiés. Corriger dans le JSON (via `02-a-valider`), revalider, régénérer. Pour un cas déjà publié, l'agent liste les cas à mettre à jour à la main dans Squash.

**Le contrôle affiche des avertissements.** Ils ne bloquent pas, mais chacun doit être lu : soit on corrige, soit on le garde volontairement (par exemple un cas suspendu à une question bloquante en attente du client).

**Deux testeurs sur le même projet ?** Un seul responsable valide. Committer après chaque étape et faire `git pull` avant de publier dans Squash.
