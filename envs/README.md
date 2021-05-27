# Virtualenv

Pour charger votre fichier contenant les variables d'environement, vous pouvez
ajouter ces lignes à la fin de `$VIRTUAL_ENV/bin/activate` :

```shell
set -a
. $HOME/itou/envs/dev.env
set +a
```
