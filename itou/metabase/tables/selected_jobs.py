from itou.metabase.tables.utils import MetabaseTable


TABLE = MetabaseTable(name="fiches_de_poste_par_candidature")
TABLE.add_columns(
    [
        {
            "name": "id_fiche_de_poste",
            "type": "integer",
            "comment": "ID fiche de poste",
            "fn": lambda o: o["selected_jobs__id"],
        },
        {
            "name": "id_candidature",
            "type": "uuid",
            "comment": "ID de la candidature",
            "fn": lambda o: o["pk"],
        },
    ]
)
