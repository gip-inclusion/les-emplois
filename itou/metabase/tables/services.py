from decimal import Decimal

from itou.insertion.models import Service
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field


TABLE = MetabaseTable(name="services_v0")
TABLE.add_columns(
    [
        get_column_from_field(get_model_field(Service, "id"), name="id"),
        get_column_from_field(get_model_field(Service, "uid"), name="uid", comment="ID public (DI)"),
        {
            "name": "structure_uid",
            "type": "varchar",
            "comment": "ID public (DI) de la structure",
            "fn": lambda o: o.structure.uid,
        },
        {
            "name": "source",
            "type": "varchar",
            "comment": "source",
            "fn": lambda o: o.source.value,
        },
        {
            "name": "source_link",
            "type": "varchar",
            "comment": "lien vers la source",
            "fn": lambda o: str(o.source_link) if o.source_link else None,
        },
        get_column_from_field(get_model_field(Service, "name"), name="name"),
        get_column_from_field(get_model_field(Service, "description"), name="description"),
        {
            "name": "duration_weekly_hours",
            "type": "numeric",
            "comment": "Volume horaire hebdomadaire",
            "fn": lambda o: Decimal(o.volume_horaire_hebdomadaire) if o.volume_horaire_hebdomadaire else None,
        },
        get_column_from_field(
            get_model_field(Service, "nombre_semaines"),
            name="duration_weeks",
            comment="Nombre de semaines",
        ),
        {
            "name": "code_insee",
            "type": "varchar",
            "comment": "Code INSEE de la commune du service",
            "fn": lambda o: o.insee_city.code_insee if o.insee_city else None,
        },
        get_column_from_field(get_model_field(Service, "is_active"), name="is_active"),
    ]
)
