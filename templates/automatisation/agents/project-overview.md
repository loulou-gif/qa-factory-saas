# project-overview.md — {{APPLICATION}}

Contexte du projet pour l'agent d'automatisation. Distinguer **faits documentés** (cahier des charges, réponses écrites), **faits observés** (exploration) et **points à confirmer**. Ne jamais transformer une information manquante en règle supposée.

## 1. Identification

| Élément | Information | Source |
|---|---|---|
| Application | {{APPLICATION}} | projet.json |
| Client | {{CLIENT}} | projet.json |
| URL de test | `BASE_URL` (ne pas écrire l'URL dans les tests) | projet.json |
| Environnement | {{ENVIRONNEMENT}} | à confirmer par l'équipe projet |
| Technologie front | À observer | exploration |
| Authentification | À observer | exploration |

## 2. Contexte fonctionnel

Résumé du cahier des charges (faits documentés, avec leurs sources `CDC §…`).

## 3. Rôles et comptes de test

| Rôle | Variable d'identifiant | Droits confirmés | Source |
|---|---|---|---|
| À compléter | `COMPTE_1_IDENTIFIANT` / `COMPTE_1_MOT_DE_PASSE` | à confirmer | |

## 4. Périmètre et actions autorisées

- Actions autorisées : {{ACTIONS_AUTORISEES}}
- Hors périmètre : …

## 5. Fonctionnalités et specs

| Fonctionnalité | Spec | Statut | Cas |
|---|---|---|---|
| | `agents/features/<fonctionnalite>.md` | BROUILLON / CONFIRMÉE | CT… |

## 6. Points à confirmer

Repris de `ambiguites.md` (questions ouvertes) et des écarts d'exploration. Une ligne par point, avec sa référence `Q-xxx`.
