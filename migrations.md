# Migrations de code en cours

Certains changements pour suivre des bonnes pratiques et éviter des anomalies
demandent trop d’efforts pour être intégrés en une seule fois, ou charger un
seul développeur de les mener à bien. Ils sont donc intégrés lorsqu’un
développeur en aperçoit l’opportunité.

Ce document met en évidence ces changements pour que les développeurs les
gardent en tête. Cette liste devrait rester courte pour éviter d’éparpiller les
efforts.

## Découpage des gros fichiers de tests

### Identification des fichiers

```sh
$ find tests -name '*.py' -exec wc --lines \{\} \; | sort --numeric-sort --reverse | head --lines=10
```

L’objectif est de ne pas dépasser environ 1 000 lignes par fichier.

## Utiliser les `factory.Trait`

Au lieu d’utiliser l’héritage pour définir un ensemble d’attributs pour
représenter une situation donnée, mieux vaut utiliser les
[Traits](https://factoryboy.readthedocs.io/en/stable/reference.html#traits),
car ils ne demandent pas de redéfinir les classes `Meta`, ni de lire plusieurs
définitions pour connaître la valeur finale des attributs.

## Déplacer les modales vers le `<body>`

Cette migration est problématique quand la modale est liée à un `{% include %}`
car on ne peut pas avoir des `{% include %}` et des `{% block %}`, mais devrait
éviter des problèmes de `z-index` lorsque le *markup* de la modale est dans un
élément avec `z-index` différent.

## Préfixer les attributs utilisé par notre JS par data-emplois-

Beaucoup de notre code JS n'utilise pas encore le préfixe `data-emplois-`.
