# Spec : choix du modèle d'IA par l'utilisateur (Paramètres › Modèles)

Statut : **à exécuter plus tard**, phase par phase. Rédigée le 2026-11-06 sur l'état de la copie produit
(`qa-produit/qa-saas`, branche `saas`). Avant d'exécuter une phase, revérifier la section 2 : le code a pu changer.

## 1. Réponse courte

**Aujourd'hui, l'utilisateur ne peut pas choisir son modèle.** Un seul modèle sert tout le serveur :

- il est fixé par l'administrateur dans `.env` (`QAF_MODELE=openrouter/<fournisseur>/<modèle>`) et lu une fois au
  démarrage (`saas/app/config.py`, `saas/demarrer.sh`) ; en changer impose de redémarrer les conteneurs ;
- une seule clé, `OPENROUTER_API_KEY`, posée dans l'environnement du conteneur **moteur** (OpenCode) via
  `saas/opencode.serveur.json` ;
- chaque tâche envoie ce même modèle à OpenCode (`saas/app/moteur.py`, `POST /session/{id}/command`, champ `model`).

Point favorable : OpenCode accepte un modèle **par commande**. Choisir parmi des modèles déjà accessibles avec la clé
du serveur est donc un petit chantier (phase A). Les clés personnelles et les modèles d'entreprise sont plus lourds
(phases B et C), surtout pour des raisons de sécurité et d'organisation, détaillées plus bas.

## 2. Ce qui empêche le choix aujourd'hui (état au 2026-11-06)

| # | Constat | Où | Conséquence |
|---|---|---|---|
| 1 | Modèle unique, global, en variable d'environnement | `config.py` (`reglages.modele`), `moteur.py` | Aucun choix possible sans redémarrage |
| 2 | Fournisseurs et clés chargés par OpenCode **au démarrage** | `config_moteur.py`, `OPENCODE_CONFIG_CONTENT` | Une clé ajoutée depuis l'interface n'est pas vue par le moteur |
| 3 | La clé vit **dans le conteneur moteur**, où l'agent peut lancer `python *` avec accès réseau | `opencode.serveur.json` (permission `bash`) | Une clé d'utilisateur placée là pourrait être lue et envoyée ailleurs par un cahier des charges piégé (injection de consignes) |
| 4 | Pas de notion d'organisation (tous les comptes partagent tout) ; rôles définis mais peu appliqués | `db.py`, `securite.py` | Impossible de dire « modèles de l'entreprise X » ou « clé payée par l'entreprise X » |
| 5 | Les skills demandent un modèle qui appelle des outils, suit des consignes longues et lit de longs documents | `docs/OPENCODE.md`, `taches.analyse_sans_resultat` | Un modèle léger ou gratuit échoue souvent : on ne peut pas proposer « n'importe quel modèle » sans qualification |

## 3. Objectif et périmètre

Un onglet **Modèles** dans les **Paramètres** (à côté de l'onglet Squash) où :

1. l'utilisateur voit les modèles connus, avec leur niveau de compatibilité, et choisit son modèle par défaut ;
2. il peut choisir un autre modèle au lancement d'une analyse ou d'une correction ;
3. (phase B) il peut enregistrer **ses propres clés d'API** (OpenRouter, OpenAI, Anthropic, Mistral, Google…) ;
4. (phase C) un administrateur d'organisation déclare les **modèles de l'entreprise** : Azure OpenAI, AWS Bedrock,
   Google Vertex, ou un point d'accès compatible OpenAI hébergé en interne (vLLM, Ollama, LiteLLM…).

Hors périmètre : héberger des modèles nous-mêmes ; facturer l'usage ; choisir un modèle différent par étape d'une
même tâche (le `small_model` d'OpenCode reste aligné sur le modèle choisi).

## 4. Découpage en phases

| Phase | Contenu | Prérequis (maturité du projet) | Risque |
|---|---|---|---|
| **A** | Catalogue tenu par l'administrateur, clé du serveur ; choix par l'utilisateur (défaut et au lancement) | Aucun | Faible |
| **B** | Clés personnelles (« apportez votre clé ») | Passerelle IA (section 6) **et** moteur sans accès réseau direct | Moyen |
| **C** | Modèles d'entreprise, gérés par un administrateur d'organisation | Organisations (multi-entreprise) et rôles appliqués, plus la phase B | Élevé |

Ne pas commencer B avant d'avoir corrigé le constat n° 3. Ne pas commencer C sans organisations : sans elles, un
« modèle d'entreprise » serait visible et utilisable par tous les comptes du serveur.

## 5. Phase A : catalogue et choix du modèle

### Données (`saas/app/db.py`)

```sql
CREATE TABLE IF NOT EXISTS modeles (
  id INTEGER PRIMARY KEY,
  reference TEXT NOT NULL UNIQUE,      -- identifiant OpenCode, ex. openrouter/anthropic/claude-sonnet-4.5
  libelle TEXT NOT NULL,               -- nom affiché
  fournisseur TEXT NOT NULL,           -- openrouter, simulation…
  niveau TEXT NOT NULL CHECK (niveau IN ('recommande','compatible','essai')),
  contexte_k INTEGER,                  -- taille de contexte, en milliers de jetons (information)
  prix_entree REAL, prix_sortie REAL,  -- USD par million de jetons (information)
  notes TEXT,
  actif INTEGER NOT NULL DEFAULT 1,
  maj_le TEXT NOT NULL
);
ALTER TABLE utilisateurs ADD COLUMN modele_id INTEGER REFERENCES modeles(id);  -- modèle par défaut de la personne
```

- Au démarrage, si la table est vide, y insérer `QAF_MODELE` comme modèle `recommande` : le comportement actuel reste
  identique tant que personne ne touche au catalogue.
- Modèle d'une tâche : choisi au lancement, sinon celui de l'utilisateur, sinon le premier `recommande` actif.
  Il est **enregistré dans `taches.parametres.modele`** : relancer une tâche ou lire son journal dit toujours quel modèle a produit quoi.

### Moteur (`saas/app/moteur.py`)

- `executer(base, tid, commande, arguments, modele)` : `modele` remplace `reglages.modele` dans `POST /session/{id}/command`.
- Contrôle avant envoi : la référence doit être un modèle **actif du catalogue** (jamais une chaîne venue du navigateur).
- `demarrer.sh` : `QAF_MODELE` reste obligatoire (modèle de secours et `small_model` d'OpenCode).
- Vérifier sur la version d'OpenCode installée que le champ `model` de `/session/{id}/command` est bien pris en compte
  pour un modèle différent de celui de la configuration (test en simulation : deux faux modèles déclarés dans
  `dev/opencode.simulation.json`).

### Interface

- Paramètres devient une page à onglets : `/parametres/squash` et `/parametres/modeles` (le lien « Squash » du menu
  devient « Paramètres »).
- **Onglet Modèles (utilisateur)** : liste des modèles actifs avec leur nom, leur fournisseur, une pastille de niveau
  (« Recommandé », « Compatible », « À l'essai »), le contexte, le prix indicatif et des notes courtes. Un bouton radio
  « Mon modèle par défaut ». Le texte d'aide dit clairement qu'un modèle « À l'essai » peut échouer sur l'analyse.
- **Lancement d'une analyse ou d'une correction** : une ligne discrète « Modèle : *Nom* · changer » ouvre une liste
  déroulante limitée au catalogue.
- **Administration (rôle admin)** : ajouter, modifier, désactiver un modèle. Le bouton « Vérifier » interroge
  `GET https://openrouter.ai/api/v1/models` (avec la clé du serveur) et contrôle que le modèle existe et accepte les outils
  (`supported_parameters` contient `tools`) ; il remplit le contexte et les prix.
- **Qualification** : un modèle passe de « À l'essai » à « Compatible » ou « Recommandé » après l'analyse de référence
  SauceDemo (procédure déjà décrite dans `saas/README.md`, « Choisir le modèle »). Plus tard, cette procédure pourra
  être automatisée en tâche « qualifier ».

### Critères d'acceptation (A)

- Sans rien configurer, tout fonctionne comme avant (modèle `QAF_MODELE`).
- Deux utilisateurs avec deux modèles par défaut différents lancent chacun une analyse : chaque session OpenCode
  utilise le bon modèle (vérifié dans le journal de la tâche et dans le compte rendu OpenCode).
- Un modèle désactivé n'est plus proposé ; une tâche déjà terminée garde son modèle dans l'historique.
- Envoyer une référence de modèle hors catalogue dans la requête renvoie 400.
- Le coût affiché par tâche (`cout_usd`) reste juste quel que soit le modèle.

### Tests

- `tests/test_modeles.py` sans moteur : catalogue, préférence, choix au lancement, refus d'un modèle hors catalogue,
  droits d'administration.
- `test_parcours.py` (Linux ou Docker) : deux faux modèles ; vérifier lequel a répondu.

## 6. Phase B : clés personnelles

### Pourquoi une passerelle

La clé d'un utilisateur **ne doit jamais entrer dans le conteneur moteur** (constat n° 3). On ajoute donc une
**passerelle IA** dans le conteneur web : un point d'accès compatible OpenAI (`/ia/v1/chat/completions`, avec flux
SSE) que seul le moteur peut joindre, sur le réseau Docker interne. OpenCode est configuré avec un unique fournisseur
`qaf` qui pointe vers cette passerelle. Pour chaque requête, la passerelle :

1. identifie la tâche ;
2. retrouve le modèle et la clé de la personne qui a lancé la tâche ;
3. déchiffre la clé, appelle le vrai fournisseur et renvoie le flux tel quel ;
4. note les jetons et le coût sur la tâche.

**Étape 0 (à faire avant tout développement) : trouver comment la passerelle reconnaît la tâche.** Trois pistes, par ordre de préférence :

1. OpenCode transmet un identifiant de session au fournisseur (en-tête) : la passerelle fait le lien session → tâche,
   puisque `taches.session_id` est déjà enregistré.
2. Modèles déclarés dynamiquement : la configuration du fournisseur `qaf` liste les modèles du catalogue, et la tâche
   est retrouvée par la session OpenCode active pour ce modèle et ce projet. Une seule tâche est active par projet ;
   à vérifier si plusieurs tâches tournent en parallèle sur le serveur.
3. Un processus OpenCode par tâche, lancé avec une clé de passerelle à usage unique. C'est la piste la plus sûre mais
   aussi la plus lourde : quelques secondes de démarrage et environ 300 Mo par tâche.

La décision est prise sur la base d'un essai réel avec la version d'OpenCode installée, et notée dans ce document.

### Isolement du moteur (obligatoire avant B)

- Conteneur moteur sans accès Internet direct : réseau Docker `internal: true`, joignable par le web seulement.
  Ses seules sorties : la passerelle et, si besoin, le registre npm au moment de la construction de l'image.
- Les clés de fournisseurs sortent de `opencode.serveur.json` : le moteur ne connaît plus que la passerelle.
- Revoir les permissions `bash` de l'agent (`python *`) : sans réseau, une fuite devient impossible même si un document piégé le pousse à essayer.

### Données et interface

- Table `cles_ia (utilisateur_id, fournisseur, secret_chiffre, verifiee_le, maj_le)` : chiffrement Fernet, comme
  `connexions_squash` (`app/connexions.py`), avec la même règle : la clé n'est jamais réaffichée et n'apparaît jamais
  dans le journal d'audit.
- Onglet Modèles, section **« Mes clés d'API »** : une ligne par fournisseur pris en charge (OpenRouter, OpenAI,
  Anthropic, Mistral, Google). Pour chacun : champ de la clé, bouton « Tester et enregistrer » (appel de liste des
  modèles ou requête minimale), état « Vérifiée le… », et « Supprimer ».
- Les modèles du catalogue indiquent « avec la clé du service » ou « avec votre clé ». Un modèle qui exige une clé
  personnelle absente est grisé, avec le lien « Ajouter une clé ».
- Les frais sont imputés au compte du fournisseur de l'utilisateur. Le coût par tâche reste affiché ; ajouter un
  plafond mensuel facultatif par utilisateur.

### Critères d'acceptation (B)

- Une analyse lancée avec une clé personnelle n'utilise jamais la clé du serveur, et inversement (vérifié par un faux
  fournisseur qui enregistre les en-têtes reçus, comme `tests/faux_squash.py`).
- Depuis le conteneur moteur, `python -c "import urllib.request; urllib.request.urlopen('https://example.com')"` échoue.
- La clé ne figure ni dans la base en clair, ni dans les journaux, ni dans l'environnement du moteur.
- Une clé refusée par le fournisseur donne un message clair (réutiliser `moteur.expliquer_erreur_modele`).

## 7. Phase C : modèles de l'entreprise

Prérequis : une **organisation** par entreprise, avec ses utilisateurs, ses projets et un rôle « administrateur
d'organisation » réellement contrôlé à chaque route. Ce chantier dépasse les modèles : c'est le premier point de
l'audit du SaaS.

- Table `fournisseurs_organisation (organisation_id, type, libelle, point_acces, secret_chiffre, options_json, actif)`, avec
  `type` parmi `openai_compatible`, `azure_openai`, `bedrock` et `vertex`.
- La passerelle de la phase B appelle ces fournisseurs. Un point d'accès interne à l'entreprise (vLLM, Ollama…) est
  soumis à la même garde réseau que Squash (`connexions.verifier_reseau`, `reseau_public.mjs`) : refusé sur le service
  public, autorisé seulement sur une installation dans l'entreprise (`QAF_SQUASH_RESEAU_PRIVE`, à renommer en
  `QAF_RESEAU_PRIVE`).
- L'administrateur d'organisation peut imposer une politique : « seulement les modèles de l'entreprise », ou
  « modèles de l'entreprise et clés personnelles ».
- Onglet Modèles : section « Modèles de l'entreprise », en lecture seule pour les utilisateurs, et modifiable par
  l'administrateur de l'organisation.

## 8. Sécurité, en résumé

- Aucun secret d'IA dans le conteneur moteur à partir de la phase B ; le moteur n'a plus d'accès réseau direct.
- Les secrets sont chiffrés au repos, jamais réaffichés et jamais journalisés ; ils sont testés avant d'être enregistrés.
- Le modèle utilisé est toujours choisi dans un catalogue côté serveur, jamais pris tel quel depuis le navigateur.
- Le modèle et le coût sont tracés sur chaque tâche (audit).
- Pour un usage grand public, signaler que les documents partent chez le fournisseur choisi. Recommander les options
  « sans conservation des données » (Zero Data Retention chez OpenRouter, contrats entreprise chez les autres).

## 9. Questions à trancher avant exécution

1. Phase A : l'utilisateur choisit-il seulement son modèle par défaut, ou aussi à chaque analyse ? (La spec prévoit les deux.)
2. Quels fournisseurs pour les clés personnelles au lancement de B ? Proposition : OpenRouter seul d'abord, qui donne
   accès à la plupart des modèles avec une seule clé, puis OpenAI et Anthropic en direct.
3. Le service public paie-t-il des modèles avec sa propre clé (offre incluse), ou exige-t-il une clé de l'utilisateur ?
   La réponse décide si la clé du serveur reste après la phase B.
4. Quel modèle de facturation pour les organisations (phase C) ? Hors technique, mais cela change les plafonds et le suivi des coûts.

## 10. Ordre d'exécution conseillé

1. Phase A : environ 2 à 3 jours, avec les tests.
2. Organisations et rôles : le chantier n° 1 de l'audit, nécessaire au produit de toute façon.
3. Étape 0 de B (essai OpenCode), puis isolement réseau du moteur, puis passerelle et clés personnelles.
4. Phase C.
