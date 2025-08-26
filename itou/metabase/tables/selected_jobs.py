from itou.job_applications.models import JobApplication
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field


TABLE = MetabaseTable(name="fiches_de_poste_par_candidature")
TABLE.add_columns(
    [
        get_column_from_field(
            get_model_field(JobApplication.selected_jobs.through, "jobdescription"),
            name="id_fiche_de_poste",
            comment="ID fiche de poste",
        ),
        get_column_from_field(
            get_model_field(JobApplication.selected_jobs.through, "jobapplication"),
            name="id_candidature",
            comment="ID de la candidature",
        ),
    ]
)
