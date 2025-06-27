# Style de programmation (coding style)

La majeure partie est assurée par les outils automatiques (ruff, …), qui
sauront porter les non-conformités à votre attention. Il reste quelques
conventions listées dans ce document.

## Fichiers de modèles Django

Dans le fichier des modèles, commencer par définir les éventuelles classes de
`Manager` ou de `QuerySet`, puis le modèle correspondant.

## Ordonnancement des méthodes et classes spéciales

1. Constantes de classe
2. Variables de classe (les champs de la base de données)
3. Managers éventuels
4. `Meta`
5. Méthodes magiques (`__str__` , …)
6. Méthodes CRUD de l'ORM (`save`, …)
7. Propriétés
8. Méthodes statiques
9. Méthodes de classe
10. Méthodes

Penser à :

- l'admin
- les [factories](https://factoryboy.readthedocs.io/)
- les `ModelForm`s

## Utilisation systématique de l’argument `of` pour `select_for_update()`

Le comportement de `select_for_update()` est de verrouiller toutes les lignes
associées à une requête, [y compris celles des
`select_related()`](https://docs.djangoproject.com/en/dev/ref/models/querysets/#:~:text=locks%20all%20rows%20that%20are%20selected%20by%20the%20query).

Afin de limiter la contention imprévue, il est recommandé de préciser quelles
lignes doivent être verrouillées via l’argument `of`.
