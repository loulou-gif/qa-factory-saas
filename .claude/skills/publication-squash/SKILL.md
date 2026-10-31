---
name: publication-squash
description: Publie dans Squash TM les exigences et cas de tests classiques validés de projets/<projet>/03-valide/cas-de-tests.json, via le MCP squash-tm (simulation puis publication, sans doublon). À utiliser pour /publier.
---

# Publication dans Squash TM

Outil : serveur MCP `squash-tm` (fork `squash-tm-mcp`, vérifié sur Squash TM 9.0.0). Outils utilisés : `validate_publication_file`, `publish_validated_test_cases`, et en lecture `get_project`, `get_requirement`, `get_test_case`.

## Préconditions (toutes obligatoires, sinon s'arrêter et dire pourquoi)

1. `projets/<projet>/03-valide/cas-de-tests.json` existe. S'il n'est que dans `02-a-valider`, ce n'est pas validé : ne rien publier.
2. `python outils/controle.py <projet> --dossier 03-valide` : 0 erreur.
3. `projet.json` → `squash.projet_id` est renseigné et égal à `projet.id` du JSON. Sinon, le signaler : le projet Squash doit être créé à la main (création par API réservée aux licences Premium) puis son ID reporté dans `projet.json`.
4. `get_project` avec cet ID répond : le projet existe et le compte y a accès.
5. Questions **bloquantes ouvertes** dans `03-valide/ambiguites.md` : les lister et demander au responsable du projet s'il publie quand même (les cas concernés seront publiés tels quels).

## Déroulé

1. `validate_publication_file` avec le chemin **absolu** du JSON validé. 0 erreur attendue.
2. **Simulation** : `publish_validated_test_cases` avec
   - `filePath` : chemin absolu de `03-valide/cas-de-tests.json` ;
   - `mappingFilePath` : chemin absolu de `04-livrables/squash/correspondance.json` ;
   - `apply` : `false`.
3. Présenter le plan au responsable du projet : nombre de dossiers, exigences et cas à créer, éléments déjà présents, éléments à recréer. Estimer la durée : environ 15 secondes par création sur l'instance Squash actuelle.
4. Attendre son accord **explicite** dans la conversation. Sans accord, s'arrêter là.
5. **Publication** : même appel avec `apply: true`.
6. Si l'appel s'arrête sur une erreur : tout ce qui a été créé est déjà dans le fichier de correspondance. Lire l'erreur Squash, corriger la cause (souvent un champ personnalisé obligatoire ou un code de nature/catégorie absent de l'instance), puis relancer : la publication reprend sans doublon.
7. Vérifier un échantillon en lecture : `get_requirement` sur une exigence et `get_test_case` sur un cas (pas, jeux de données, `verified_requirements`).
8. Journal : `| date | publier | N dossiers, N exigences, N cas créés | 04-livrables/squash/correspondance.json |`.

## Compte rendu

- ce qui a été créé, avec les dossiers Squash (noms des fonctionnalités) ;
- ce qui existait déjà ;
- les avertissements (questions bloquantes publiées, cas sans exigence…) ;
- rappel : `correspondance.json` est à conserver avec le projet (les projets ne sont pas sur Git) ; republier ce projet depuis ce poste, ou transmettre ce fichier avec le dossier du projet.

## Interdits

- Publier depuis `02-a-valider`.
- Passer `apply: true` sans accord explicite du responsable du projet dans la conversation en cours.
- Modifier ou supprimer quoi que ce soit dans Squash (les outils destructifs sont bloqués par le MCP : ne pas demander leur déblocage).
- Supprimer ou éditer à la main `correspondance.json` : c'est lui qui empêche les doublons.

## Mise à jour après une nouvelle validation

Si le responsable du projet valide une nouvelle version du JSON (nouveaux cas) : relancer simplement la publication. Seuls les identifiants absents de la correspondance sont créés. Un cas **modifié** déjà publié n'est **pas** mis à jour dans Squash (limite volontaire du MCP) : le signaler et lister les cas concernés pour une mise à jour manuelle dans Squash.
