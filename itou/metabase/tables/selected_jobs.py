from itou.metabase.tables.utils import MetabaseTable, hash_content


TABLE = MetabaseTable(name="fiches_de_poste_par_candidature")
TABLE.add_columns(
    [
        {
            "name": "id_fiche_de_poste",
            "type": "int",
            "comment": "ID fiche de poste",
            "fn": lambda o: o["selected_jobs__id"],
        },
        {
            "name": "id_candidature",
            "type": "varchar",
            "comment": "ID de la candidature",
            "fn": lambda o: o["pk"],
        },
        {
            # TODO @dejafait : eventually drop this obsolete field
            "name": "id_anonymisé_candidature",
            "type": "varchar",
            "comment": "ID anonymisé de la candidature",
            "fn": lambda o: hash_content(o["pk"]),
        },
    ]
)
