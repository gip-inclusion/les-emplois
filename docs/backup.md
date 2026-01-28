# Sauvegarde

La base de données est sauvegardée toutes les nuits. La procédure pour obtenir
une sauvegarde est décrite dans le _repository_ privé
[itou-backups](https://github.com/gip-inclusion/itou-backups/).

## Restaurer une sauvegarde localement

**Les sauvegardes contiennent des données sensibles et ne doivent être
utilisées localement qu’en dernier recours**.

Une fois leur utilisation terminée :

- supprimer le fichier de sauvegarde (idéalement via
  `shred -u /path/to/dump.db`)
- `dropdb` la base où les données ont été restaurées

Pour restaurer :

```console
pg_restore --dbname="${PGDATABASE}" --format=c --clean --no-owner --jobs="$(nproc --all --ignore=1)" --verbose "${BACKUP_FILE}"
```
