<!-- Fichier généré par outils/rendre_revue.py à partir de cas-de-tests.json — NE PAS MODIFIER. empreinte: b3dafa43ba689363 -->
# Cas de tests — SauceDemo (version 2)

Vue de relecture, en lecture seule. Pour modifier : `cas-de-tests.xlsx` ou `cas-de-tests.docx` (l'un ou l'autre), puis `/corriger saucedemo` ; ou directement `/corriger saucedemo <demande>`.

Sources analysées : 01-entrant/cahier-des-charges.md

## Synthèse

| Indicateur | Valeur |
|---|---|
| Fonctionnalités | 5 |
| Exigences | 17 |
| Cas de tests | 27 |
| Cas négatif | 11 |
| Cas nominal | 16 |
| Type de test : test fonctionnel (adéquation fonctionnelle) | 25 |
| Type de test : test de sécurité | 2 |
| Technique : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA) | 11 |
| Technique : Critères d'acceptation (CTFL v4.0 §4.5.2) | 1 |
| Technique : Estimation d'erreurs (CTFL v4.0 §4.4.1) | 1 |
| Technique : Partitions d'équivalence (CTFL v4.0 §4.2.1) | 9 |
| Technique : Tables de décision (CTFL v4.0 §4.2.3) | 2 |
| Technique : Test de transition d'états (CTFL v4.0 §4.2.4) | 3 |
| Questions ouvertes | 11 (dont bloquantes : 2) |

## Stratégie de types de tests (ISTQB)

Chaque type de test ISTQB est examiné : retenu, non retenu (avec la raison) ou à confirmer (avec une question).

| ID | Type de test | Décision | Niveau | Approche | Objectif | Exigences | Cas | Outil | Justification | Questions |
|---|---|---|---|---|---|---|---|---|---|---|
| TT-01 | Test fonctionnel (adéquation fonctionnelle) | Retenu | systeme | Cas de tests de ce fichier | Vérifier les règles fonctionnelles des sections 2 à 5 du CDC (authentification, catalogue, panier, commande). | EX-001, EX-002, EX-003, EX-004, EX-005, EX-006, EX-007, EX-008, EX-009, EX-010, EX-011, EX-012, EX-013, EX-014, EX-015 | CT0001, CT0002, CT0003, CT0004, CT0005, CT0006, CT0007, CT0009, CT0011, CT0012, CT0013, CT0014, CT0015, CT0016, CT0017, CT0018, CT0019, CT0020, CT0021, CT0022, CT0023, CT0024, CT0025, CT0026, CT0027 | Squash TM (exécution manuelle), Playwright (automatisation) | CDC §2 à §5 : exigences fonctionnelles explicites. |  |
| TT-02 | Test de sécurité | Retenu | systeme | Cas de tests de ce fichier | Vérifier le masquage du mot de passe et l'impossibilité d'accéder aux pages internes sans session. | EX-017, EX-005 | CT0008, CT0010 | Playwright | CDC §6.2 (mots de passe jamais en clair) et §2.5 (pas d'accès aux pages internes après déconnexion). Aucun test intrusif (injection, force brute) sans autorisation écrite : non demandé par le CDC. |  |
| TT-03 | Test de performance (rendement) | À confirmer | systeme | Campagne dédiée | Mesurer les temps de réponse des pages principales (connexion, catalogue, panier, commande) sous la charge attendue. | EX-016 |  | Gatling | CDC §6.1 « l'application doit être rapide » : exigence présente mais non mesurable ; seuils, pages et charge à définir avant toute campagne. | Q-004 |
| TT-04 | Test de compatibilité | À confirmer |  |  |  |  |  |  | Le CDC ne précise ni navigateurs ni appareils supportés ; une boutique en ligne est généralement utilisée sur plusieurs navigateurs et sur mobile. | Q-010 |
| TT-05 | Test d'utilisabilité (dont accessibilité) | À confirmer |  |  |  |  |  |  | Le CDC ne formule aucune exigence d'ergonomie ni d'accessibilité (RGAA, WCAG). | Q-011 |
| TT-06 | Test de fiabilité | Non retenu |  |  |  |  |  |  | Aucune exigence de disponibilité, de tolérance aux pannes ou de reprise dans le CDC ; environnement de démonstration public. |  |
| TT-07 | Test de maintenabilité | Non retenu |  |  |  |  |  |  | Relève de l'équipe de développement (revue de code, analyse statique) ; aucun accès au code source. |  |
| TT-08 | Test de portabilité | Non retenu |  |  |  |  |  |  | Application web hébergée par le fournisseur : aucune installation ni migration à tester d'après le CDC. |  |
| TT-09 | Test de confirmation (re-test d'une anomalie corrigée) | Retenu | systeme | Cas de tests de ce fichier | Rejouer le cas qui a révélé une anomalie une fois celle-ci déclarée corrigée. |  |  | Squash TM (campagne de re-test) | Pratique standard de recette (CTFL v4.0 §2.2.3) pour chaque anomalie corrigée. |  |
| TT-10 | Test de régression | Retenu | systeme | Cas de tests de ce fichier | Rejouer à chaque nouvelle livraison les parcours principaux automatisés (smoke) puis l'ensemble des cas automatisés. |  | CT0001, CT0009, CT0011, CT0017, CT0018, CT0019, CT0021, CT0025, CT0026 | Playwright (tags @smoke et @regression) | Parcours bloquants pour le métier (importance HIGH ou VERY_HIGH) ; l'application évolue par livraisons successives. |  |

## Authentification

### Exigences

| ID | Exigence | Criticité | Source | Questions |
|---|---|---|---|---|
| EX-001 | **Se connecter avec un nom d'utilisateur et un mot de passe**<br>L'utilisateur se connecte avec un nom d'utilisateur et un mot de passe. Après connexion, il arrive sur la page « Products » qui affiche le catalogue. | CRITICAL | CDC §2.1 |  |
| EX-002 | **Rendre obligatoires le nom d'utilisateur et le mot de passe**<br>Les deux champs sont obligatoires. Si l'un d'eux est vide, un message d'erreur indique le champ manquant. | MAJOR | CDC §2.2 | Q-001 |
| EX-003 | **Refuser des identifiants incorrects**<br>Si le couple identifiant / mot de passe est incorrect, la connexion est refusée avec un message d'erreur. | CRITICAL | CDC §2.3 | Q-001 |
| EX-004 | **Refuser la connexion d'un compte verrouillé**<br>Un compte peut être verrouillé par l'administrateur. Un utilisateur verrouillé ne peut pas se connecter et un message lui indique que son compte est bloqué. | MAJOR | CDC §2.4 | Q-001, Q-002 |
| EX-005 | **Se déconnecter depuis le menu latéral**<br>L'utilisateur peut se déconnecter depuis le menu latéral. Après déconnexion, il revient sur la page de connexion et ne peut plus accéder aux pages internes sans se reconnecter. | MAJOR | CDC §2.5 |  |
| EX-017 | **Ne jamais afficher les mots de passe en clair**<br>Les mots de passe ne doivent jamais apparaître en clair à l'écran. | MAJOR | CDC §6.2 |  |

### Cas de tests

#### CT0001 — Se connecter avec un compte valide

- **Exigences** : EX-001
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : VERY_HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Avoir le lien de l'application et le compte standard JDD-001. Être déconnecté.
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Ouvrir le lien de l'application | La page de connexion affiche les champs nom d'utilisateur et mot de passe et le bouton de connexion. |
| 2 | Renseigner le nom d'utilisateur et le mot de passe du compte JDD-001 | Les deux champs sont remplis ; le mot de passe est masqué. |
| 3 | Cliquer sur le bouton de connexion | La page « Products » s'affiche avec la liste des articles du catalogue. |

#### CT0002 — Bloquer la connexion sans nom d'utilisateur

- **Exigences** : EX-002
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être sur la page de connexion. Disposer du mot de passe du compte JDD-001.
- **Jeux de données** : JDD-001
- **Questions liées** : Q-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Laisser le champ nom d'utilisateur vide et renseigner le mot de passe | Seul le champ mot de passe est rempli. |
| 2 | Cliquer sur le bouton de connexion | La connexion est refusée : l'utilisateur reste sur la page de connexion et un message d'erreur indique que le nom d'utilisateur est obligatoire. |

#### CT0003 — Bloquer la connexion sans mot de passe

- **Exigences** : EX-002
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être sur la page de connexion. Disposer du nom d'utilisateur du compte JDD-001.
- **Jeux de données** : JDD-001
- **Questions liées** : Q-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Renseigner le nom d'utilisateur et laisser le champ mot de passe vide | Seul le champ nom d'utilisateur est rempli. |
| 2 | Cliquer sur le bouton de connexion | La connexion est refusée : l'utilisateur reste sur la page de connexion et un message d'erreur indique que le mot de passe est obligatoire. |

#### CT0004 — Bloquer la connexion avec les deux champs vides

- **Exigences** : EX-002
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : MEDIUM
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être sur la page de connexion.
- **Questions liées** : Q-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Laisser les deux champs vides et cliquer sur le bouton de connexion | La connexion est refusée : l'utilisateur reste sur la page de connexion et un message d'erreur indique un champ manquant. |

#### CT0005 — Refuser un mot de passe incorrect

- **Exigences** : EX-003
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Tables de décision (CTFL v4.0 §4.2.3)
- **Prérequis** : Être sur la page de connexion. Disposer du nom d'utilisateur du compte JDD-001 et du mot de passe erroné de JDD-003.
- **Jeux de données** : JDD-001, JDD-003
- **Questions liées** : Q-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Renseigner le nom d'utilisateur du compte JDD-001 et le mot de passe erroné de JDD-003 | Les deux champs sont remplis. |
| 2 | Cliquer sur le bouton de connexion | La connexion est refusée : l'utilisateur reste sur la page de connexion et un message d'erreur s'affiche ; la page « Products » n'est pas accessible. |

#### CT0006 — Refuser un nom d'utilisateur inconnu

- **Exigences** : EX-003
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Tables de décision (CTFL v4.0 §4.2.3)
- **Prérequis** : Être sur la page de connexion.
- **Jeux de données** : JDD-003
- **Questions liées** : Q-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Renseigner le nom d'utilisateur inconnu et le mot de passe de JDD-003 | Les deux champs sont remplis. |
| 2 | Cliquer sur le bouton de connexion | La connexion est refusée : l'utilisateur reste sur la page de connexion et un message d'erreur s'affiche. |

#### CT0007 — Refuser la connexion d'un compte verrouillé — **suspendu à une question bloquante**

- **Exigences** : EX-004
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Test de transition d'états (CTFL v4.0 §4.2.4)
- **Prérequis** : Être sur la page de connexion. Disposer d'un compte verrouillé par l'administrateur (JDD-002).
- **Jeux de données** : JDD-002
- **Questions liées** : Q-001, Q-002

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Renseigner le nom d'utilisateur et le mot de passe du compte verrouillé JDD-002 | Les deux champs sont remplis. |
| 2 | Cliquer sur le bouton de connexion | La connexion est refusée et un message indique que le compte est bloqué ; la page « Products » n'est pas accessible. |

#### CT0008 — Masquer le mot de passe lors de la saisie

- **Exigences** : EX-017
- **Nature** : Nominal — **Type de test** : Test de sécurité — **Importance** : HIGH
- **Technique ISTQB** : Critères d'acceptation (CTFL v4.0 §4.5.2)
- **Prérequis** : Être sur la page de connexion. Disposer du compte JDD-001.
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Saisir le mot de passe du compte JDD-001 dans le champ mot de passe | Les caractères saisis sont remplacés par des symboles de masquage ; le mot de passe n'apparaît pas en clair. |

#### CT0009 — Se déconnecter depuis le menu latéral

- **Exigences** : EX-005
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001 et se trouver sur la page « Products ».
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Ouvrir le menu latéral | Le menu latéral s'affiche avec l'option de déconnexion. |
| 2 | Cliquer sur l'option de déconnexion | La page de connexion s'affiche. |

#### CT0010 — Interdire l'accès aux pages internes après déconnexion

- **Exigences** : EX-005
- **Nature** : Négatif — **Type de test** : Test de sécurité — **Importance** : HIGH
- **Technique ISTQB** : Test de transition d'états (CTFL v4.0 §4.2.4)
- **Prérequis** : Avoir relevé l'adresse de la page « Products » pendant une session, puis s'être déconnecté (CT0009).
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Saisir dans le navigateur l'adresse de la page « Products » relevée pendant la session | La page « Products » ne s'affiche pas : l'utilisateur est renvoyé vers la page de connexion. |

## Catalogue

### Exigences

| ID | Exigence | Criticité | Source | Questions |
|---|---|---|---|---|
| EX-006 | **Afficher le catalogue des articles**<br>La page « Products » affiche la liste des articles avec, pour chacun : image, nom, description, prix et un bouton « Add to cart ». | MAJOR | CDC §3.1 |  |
| EX-007 | **Trier le catalogue par nom ou par prix**<br>L'utilisateur peut trier la liste par nom (A à Z, Z à A) et par prix (croissant, décroissant). Le tri par défaut est par nom de A à Z. | MAJOR | CDC §3.2 |  |
| EX-008 | **Consulter la fiche détaillée d'un article**<br>Un clic sur le nom d'un article ouvre sa fiche détaillée, avec un bouton de retour vers le catalogue. | MINOR | CDC §3.3 |  |

### Cas de tests

#### CT0011 — Afficher le catalogue avec les informations de chaque article

- **Exigences** : EX-006
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001.
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Observer la page « Products » | Chaque article de la liste présente une image, un nom, une description, un prix et un bouton « Add to cart ». |

#### CT0012 — Vérifier le tri par défaut par nom de A à Z

- **Exigences** : EX-007
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : MEDIUM
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001, sans avoir modifié le tri.
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Observer l'ordre des articles de la page « Products » et le tri sélectionné | Le tri sélectionné est le tri par nom de A à Z et les noms des articles sont rangés par ordre alphabétique croissant. |

#### CT0013 — Trier les articles par nom de Z à A

- **Exigences** : EX-007
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : MEDIUM
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être connecté avec le compte JDD-001.
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Choisir le tri par nom de Z à A | Les noms des articles sont rangés par ordre alphabétique décroissant. |

#### CT0014 — Trier les articles par prix croissant

- **Exigences** : EX-007
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : MEDIUM
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être connecté avec le compte JDD-001.
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Choisir le tri par prix croissant | Les articles sont rangés du prix le plus bas au prix le plus élevé. |

#### CT0015 — Trier les articles par prix décroissant

- **Exigences** : EX-007
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : MEDIUM
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être connecté avec le compte JDD-001.
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Choisir le tri par prix décroissant | Les articles sont rangés du prix le plus élevé au prix le plus bas. |

#### CT0016 — Ouvrir la fiche d'un article et revenir au catalogue

- **Exigences** : EX-008
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : LOW
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001 et se trouver sur la page « Products ».
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Cliquer sur le nom d'un article | La fiche détaillée de l'article s'affiche avec le même nom et le même prix que dans la liste, et un bouton de retour. |
| 2 | Cliquer sur le bouton de retour | La page « Products » s'affiche de nouveau. |

## Panier

### Exigences

| ID | Exigence | Criticité | Source | Questions |
|---|---|---|---|---|
| EX-009 | **Ajouter un article au panier**<br>Le bouton « Add to cart » ajoute l'article au panier ; il devient alors « Remove ». L'icône du panier affiche le nombre d'articles. | CRITICAL | CDC §4.1 |  |
| EX-010 | **Consulter et modifier le contenu du panier**<br>Le panier liste les articles ajoutés avec leur quantité, leur nom et leur prix. L'utilisateur peut retirer un article depuis le panier. | MAJOR | CDC §4.2 | Q-009 |
| EX-011 | **Conserver le panier pendant la navigation**<br>Le contenu du panier est conservé pendant la navigation dans l'application. | MAJOR | CDC §4.3 | Q-006 |

### Cas de tests

#### CT0017 — Ajouter un article au panier depuis le catalogue

- **Exigences** : EX-009
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : VERY_HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001, panier vide.
- **Jeux de données** : JDD-001, JDD-005

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Cliquer sur « Add to cart » pour un article de la page « Products » | Le bouton de cet article devient « Remove » et l'icône du panier affiche 1. |
| 2 | Cliquer sur « Add to cart » pour un deuxième article | L'icône du panier affiche 2. |

#### CT0018 — Afficher dans le panier les articles ajoutés

- **Exigences** : EX-010
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001 et avoir ajouté les deux articles de JDD-005 au panier.
- **Jeux de données** : JDD-001, JDD-005

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Cliquer sur l'icône du panier | Le panier liste les deux articles ajoutés, chacun avec sa quantité, son nom et son prix identiques à ceux du catalogue. |

#### CT0019 — Retirer un article depuis le panier

- **Exigences** : EX-010
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001, avoir ajouté les deux articles de JDD-005 et ouvert le panier.
- **Jeux de données** : JDD-001, JDD-005
- **Questions liées** : Q-009

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Retirer le premier article depuis le panier | L'article disparaît de la liste du panier et l'icône du panier affiche 1. |

#### CT0020 — Conserver le panier pendant la navigation

- **Exigences** : EX-011
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : MEDIUM
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001 et avoir ajouté les deux articles de JDD-005.
- **Jeux de données** : JDD-001, JDD-005
- **Questions liées** : Q-006

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Ouvrir la fiche détaillée d'un autre article, puis revenir à la page « Products » | L'icône du panier affiche toujours 2 et les boutons des deux articles ajoutés affichent « Remove ». |
| 2 | Ouvrir le panier | Le panier liste toujours les deux articles ajoutés. |

## Commande

### Exigences

| ID | Exigence | Criticité | Source | Questions |
|---|---|---|---|---|
| EX-012 | **Saisir les informations de commande obligatoires**<br>Depuis le panier, le bouton « Checkout » ouvre le formulaire d'informations : prénom, nom et code postal. Les trois champs sont obligatoires. | CRITICAL | CDC §5.1 | Q-001, Q-008 |
| EX-013 | **Afficher un récapitulatif de commande au total exact**<br>L'étape suivante présente un récapitulatif : articles, moyen de paiement, mode de livraison, total hors taxes, taxes et total. Le total doit être égal à la somme des prix des articles plus les taxes. | CRITICAL | CDC §5.2 | Q-003, Q-007 |
| EX-014 | **Valider la commande et vider le panier**<br>Le bouton « Finish » valide la commande et affiche un message de confirmation. Le panier est alors vidé. | CRITICAL | CDC §5.3 | Q-007 |
| EX-015 | **Interdire une commande avec un panier vide**<br>Une commande ne doit pas pouvoir être passée avec un panier vide. | MAJOR | CDC §5.4 | Q-005 |

### Cas de tests

#### CT0021 — Passer une commande complète

- **Exigences** : EX-012, EX-013, EX-014
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : VERY_HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001 et avoir ajouté les deux articles de JDD-005 au panier. Disposer des informations de livraison JDD-004.
- **Jeux de données** : JDD-001, JDD-004, JDD-005
- **Questions liées** : Q-007

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Ouvrir le panier et cliquer sur « Checkout » | Le formulaire d'informations s'affiche avec les champs prénom, nom et code postal. |
| 2 | Renseigner le prénom, le nom et le code postal de JDD-004, puis passer à l'étape suivante | Le récapitulatif s'affiche avec les articles, le moyen de paiement, le mode de livraison, le total hors taxes, les taxes et le total. |
| 3 | Cliquer sur « Finish » | Un message de confirmation de commande s'affiche. |

#### CT0022 — Bloquer la commande sans prénom

- **Exigences** : EX-012
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être connecté avec le compte JDD-001, avoir un article dans le panier et ouvrir le formulaire d'informations.
- **Jeux de données** : JDD-001, JDD-004
- **Questions liées** : Q-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Laisser le prénom vide, renseigner le nom et le code postal de JDD-004, puis tenter de passer à l'étape suivante | Le récapitulatif ne s'affiche pas ; un message d'erreur indique que le prénom est obligatoire. |

#### CT0023 — Bloquer la commande sans nom

- **Exigences** : EX-012
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être connecté avec le compte JDD-001, avoir un article dans le panier et ouvrir le formulaire d'informations.
- **Jeux de données** : JDD-001, JDD-004
- **Questions liées** : Q-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Laisser le nom vide, renseigner le prénom et le code postal de JDD-004, puis tenter de passer à l'étape suivante | Le récapitulatif ne s'affiche pas ; un message d'erreur indique que le nom est obligatoire. |

#### CT0024 — Bloquer la commande sans code postal

- **Exigences** : EX-012
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Partitions d'équivalence (CTFL v4.0 §4.2.1)
- **Prérequis** : Être connecté avec le compte JDD-001, avoir un article dans le panier et ouvrir le formulaire d'informations.
- **Jeux de données** : JDD-001, JDD-004
- **Questions liées** : Q-001, Q-008

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Laisser le code postal vide, renseigner le prénom et le nom de JDD-004, puis tenter de passer à l'étape suivante | Le récapitulatif ne s'affiche pas ; un message d'erreur indique que le code postal est obligatoire. |

#### CT0025 — Vérifier le calcul du total du récapitulatif

- **Exigences** : EX-013
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : VERY_HIGH
- **Technique ISTQB** : Test des cas d'utilisation (CTFL v3.1 §4.2.5, CTAL-TA)
- **Prérequis** : Être connecté avec le compte JDD-001, avoir ajouté les deux articles de JDD-005 et atteint le récapitulatif avec les informations JDD-004.
- **Jeux de données** : JDD-001, JDD-004, JDD-005
- **Questions liées** : Q-003

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Relever le prix de chaque article et le total hors taxes du récapitulatif | Le total hors taxes est égal à la somme des prix des articles. |
| 2 | Relever les taxes et le total du récapitulatif | Le total est égal au total hors taxes plus les taxes affichées. |

#### CT0026 — Vider le panier après validation de la commande

- **Exigences** : EX-014
- **Nature** : Nominal — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Test de transition d'états (CTFL v4.0 §4.2.4)
- **Prérequis** : Avoir validé une commande avec « Finish » (CT0021).
- **Jeux de données** : JDD-001

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Observer l'icône du panier puis ouvrir le panier | L'icône du panier n'affiche plus de nombre et le panier ne contient aucun article. |

#### CT0027 — Empêcher une commande avec un panier vide — **suspendu à une question bloquante**

- **Exigences** : EX-015
- **Nature** : Négatif — **Type de test** : Test fonctionnel (adéquation fonctionnelle) — **Importance** : HIGH
- **Technique ISTQB** : Estimation d'erreurs (CTFL v4.0 §4.4.1)
- **Prérequis** : Être connecté avec le compte JDD-001, panier vide.
- **Jeux de données** : JDD-001
- **Questions liées** : Q-005

| # | Action | Résultat attendu |
|---|---|---|
| 1 | Ouvrir le panier vide et tenter de lancer la commande | La commande ne peut pas être passée : le récapitulatif et le message de confirmation de commande ne sont pas accessibles. |

## Exigences non fonctionnelles

### Exigences

| ID | Exigence | Criticité | Source | Questions |
|---|---|---|---|---|
| EX-016 | **Offrir des temps de réponse rapides**<br>L'application doit être rapide. | MINOR | CDC §6.1 | Q-004 |

### Cas de tests

