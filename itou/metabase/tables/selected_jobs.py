from operator import attrgetter

from itou.metabase.tables.utils import MetabaseTable


TABLE = MetabaseTable(name="fiches_de_poste_par_candidature")
TABLE.add_columns(
    [
        {
            "name": "id_fiche_de_poste",
            "type": "integer",
            "comment": "ID fiche de poste",
            "fn": attrgetter("jobdescription_id"),
        },
        {
            "name": "id_candidature",
            "type": "uuid",
            "comment": "ID de la candidature",
            "fn": attrgetter("jobapplication_id"),
        },
    ]
)
