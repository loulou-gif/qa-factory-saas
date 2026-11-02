---
name: interface-qa-factory
description: Règles de conception de l'interface web de QA Factory (saas/app) aux couleurs de Synelia — simplicité, un seul geste principal par écran, cas de tests rendus digestes, animations douces. À utiliser pour toute création ou modification d'une page, d'un gabarit ou du style de l'application.
---

# Interface QA Factory (Synelia)

L'interface sert des testeurs, pas des développeurs. Elle doit se prendre en main sans formation : chaque écran fait **une** chose, et la chose à faire se voit immédiatement. Cette skill complète les principes généraux de conception (palette réfléchie, typographie intentionnelle, retenue, autocritique par captures d'écran).

## Le parcours (ne pas l'alourdir)

1. **Accueil** : un seul grand rectangle de dépôt, une icône au centre, une phrase. Déposer les fichiers lance l'analyse : pas de formulaire, pas de bouton « Lancer ». Le nom du projet se déduit du fichier.
2. **Génération** : le même rectangle devient la barre de progression (il se remplit), puis affiche « Génération terminée » avec une coche qui se dessine, et redirige vers les fichiers produits.
3. **Fichiers produits** : une liste courte (cas de tests, questions pour le client, jeux de données ; Excel et Word en téléchargement discret). Une seule action principale selon l'état.
4. **Relecture** : les cas se lisent et se modifient sur place. Un seul bouton, « Enregistrer », qui enregistre **et valide** : il n'y a plus d'étape de validation par un responsable.
5. **Squash** : « Envoyer dans Squash », puis une confirmation qui dit exactement ce qui sera créé.

Toute nouvelle fonction doit trouver sa place dans ce parcours sans ajouter d'écran ni de bouton principal. Ce qui est rare (administration, téléchargements, retour en relecture) reste en lien discret.

## Couleurs (tokens CSS dans `statique/app.css`)

| Token | Valeur | Usage |
|---|---|---|
| `--violet` | `#675AA2` | Violet Synelia : action principale, titres, éléments actifs |
| `--violet-fonce` | `#4A3F82` | Survol et appui du bouton principal, texte sur fond clair violet |
| `--ciel` | `#8CD1F2` | Bleu ciel Synelia : remplissage de la progression, zone de dépôt survolée, repères |
| `--ciel-pale` | `#EAF6FC` | Fond de la zone de dépôt active, sélection |
| `--encre` | `#262338` | Texte courant (légèrement violacé, jamais noir pur) |
| `--gris` | `#6E6A80` | Texte secondaire |
| `--trait` | `#E4E2EE` | Bordures, séparateurs |
| `--fond` | `#F7F7FB` | Fond de page |
| `--succes` | `#2F8F6B` | Validé, envoyé |
| `--alerte` | `#B7791F` | Question bloquante, à vérifier |
| `--erreur` | `#C0392B` | Échec |

Le violet porte l'action ; le bleu ciel porte le mouvement et le progrès. Jamais de dégradé décoratif, jamais d'autre teinte vive.

## Typographie

Nunito (variable, hébergée dans `statique/polices/`, licence OFL) : ses formes arrondies rappellent le logo Synelia. Une seule famille. Échelle : 32 / 22 / 17 / 15 / 13 px ; graisses 400 (texte), 650 (libellés), 800 (titres). Phrases en casse normale, jamais de libellés tout en majuscules.

## Rendre les cas de tests digestes

Un cahier de tests fait des dizaines de cas : ne jamais tout déplier.
- En tête : **une phrase** de synthèse (« 27 cas sur 5 fonctionnalités. 2 questions attendent la réponse du client. »).
- Les fonctionnalités en onglets, chacun avec son nombre de cas.
- Un cas = **une ligne** repliée : numéro, titre, nature (nominal, négatif, limite). Le reste (prérequis, étapes, technique ISTQB, exigences) n'apparaît qu'au dépliage.
- Les étapes en deux colonnes « Je fais » / « Je dois voir », éditables sur place.
- Les métadonnées techniques (technique ISTQB, type de test, codes) sont visibles mais discrètes ; jamais de code brut (`NAT_FUNCTIONAL_TESTING`) à l'écran.
- Les questions pour le client : une carte par question, la question en clair, la gravité en pastille, le reste replié.

## Boutons et textes

- Un bouton principal par écran au plus (violet plein). Les autres actions sont des liens.
- Le libellé dit ce qui se passe : « Enregistrer », « Envoyer dans Squash ». Le message qui suit reprend le même verbe : « Enregistré », « Envoyé dans Squash ».
- Les erreurs disent quoi faire, sans s'excuser : « Le fichier est ouvert dans Excel : fermez-le puis recommencez. »
- Les confirmations sont réservées aux actions vers l'extérieur (Squash) et chiffrent ce qui va se passer.

## Mouvement

- Un moment orchestré : le rectangle de dépôt qui se remplit, puis la coche qui se dessine. Le reste est sobre.
- Animations courtes (180 à 400 ms), courbe douce (`cubic-bezier(.2,.7,.2,1)`), uniquement en réponse à un geste ou pour montrer un changement d'état : dépliage d'un cas, apparition d'un message, glisser-déposer.
- La progression avance en continu (jamais de saut brutal) et n'affiche 100 % qu'à la fin réelle.
- `prefers-reduced-motion` : les transitions deviennent instantanées.

## Qualité minimale

Fonctionne au clavier (focus visible violet), lisible sur un écran de portable comme sur un téléphone, contrastes suffisants (texte blanc seulement sur `--violet` ou plus foncé). Avant de livrer une page : faire une capture et retirer un élément.
