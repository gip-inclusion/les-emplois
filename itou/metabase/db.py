"""
Helper methods for manipulating tables used by both populate_metabase_emplois and populate_metabase_fluxiae scripts.
"""
import copy
import gc
import os
import urllib

import httpx
import psycopg
from django.conf import settings
from django.utils import timezone
from psycopg import sql

from itou.metabase.utils import chunked_queryset, compose, convert_boolean_to_int


class MetabaseDatabaseCursor:
    def __init__(self):
        self.cursor = None
        self.connection = None

    def __enter__(self):
        self.connection = psycopg.connect(
            host=settings.METABASE_HOST,
            port=settings.METABASE_PORT,
            dbname=settings.METABASE_DATABASE,
            user=settings.METABASE_USER,
            password=settings.METABASE_PASSWORD,
            keepalives=1,
            keepalives_idle=30,
            keepalives_interval=5,
            keepalives_count=5,
        )
        self.cursor = self.connection.cursor()
        return self.cursor, self.connection

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()


def get_current_dir():
    return os.path.dirname(os.path.realpath(__file__))


def get_new_table_name(table_name):
    return f"z_new_{table_name}"


def get_old_table_name(table_name):
    return f"z_old_{table_name}"


def rename_table_atomically(from_table_name, to_table_name):
    """
    Rename from_table_name to to_table_name.
    Most of the time, we replace an existing table, so we will first rename
    to_table_name to z_old_<to_table_name>.
    This allows us to take our time filling the new table without locking the current one.
    Note that when the old table z_old_<to_table_name> is deleted, all its obsolete airflow staging views
    are deleted as well, they will be rebuilt by the next run of the airflow DAG `dbt_daily`.
    """

    with MetabaseDatabaseCursor() as (cur, conn):
        # CASCADE will drop airflow staging views (e.g. stg_structures) as well.
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(get_old_table_name(to_table_name)))
        )
        conn.commit()
        cur.execute(
            sql.SQL("ALTER TABLE IF EXISTS {} RENAME TO {}").format(
                sql.Identifier(to_table_name),
                sql.Identifier(get_old_table_name(to_table_name)),
            )
        )
        cur.execute(
            sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                sql.Identifier(from_table_name),
                sql.Identifier(to_table_name),
            )
        )
        conn.commit()
        # CASCADE will drop airflow staging views (e.g. stg_structures) as well.
        cur.execute(
            sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(get_old_table_name(to_table_name)))
        )
        conn.commit()


def create_table(table_name: str, columns: list[str, str], reset=False):
    """Create table from columns names and types"""
    with MetabaseDatabaseCursor() as (cursor, conn):
        if reset:
            cursor.execute(sql.SQL("DROP TABLE IF EXISTS {table_name}").format(table_name=sql.Identifier(table_name)))
        create_table_query = sql.SQL("CREATE TABLE IF NOT EXISTS {table_name} ({fields_with_type})").format(
            table_name=sql.Identifier(table_name),
            fields_with_type=sql.SQL(",").join(
                [sql.SQL(" ").join([sql.Identifier(col_name), sql.SQL(col_type)]) for col_name, col_type in columns]
            ),
        )
        cursor.execute(create_table_query)
        conn.commit()


def build_dbt_daily():
    # FIXME(vperron): this has to be moved to DBT seeds.
    create_unversioned_tables_if_needed()
    response = httpx.post(
        urllib.parse.urljoin(settings.AIRFLOW_BASE_URL, "api/v1/dags/dbt_daily/dagRuns"),
        json={"conf": {}},
    )
    response.raise_for_status()


def build_dbt_weekly():
    # FIXME(vperron): this has to be moved to DBT seeds.
    create_unversioned_tables_if_needed()
    response = httpx.post(
        urllib.parse.urljoin(settings.AIRFLOW_BASE_URL, "api/v1/dags/dbt_weekly/dagRuns"),
        json={"conf": {}},
    )
    response.raise_for_status()


def create_unversioned_tables_if_needed():
    """
    Unfortunately some tables are not versioned yet as they are still managed manually by our data analysts.
    This becomes a problem when trying to run all requests on a local empty database.
    The present function creates these unversioned tables without any content, at least now all the requests
    can complete locally and we have a good visibility of how many tables are left to be automated.
    """
    with MetabaseDatabaseCursor() as (cur, conn):
        create_table_sql_requests = """
            /* TODO @defajait DROP ASAP - use codes_insee_vs_codes_postaux instead */
            CREATE TABLE IF NOT EXISTS "commune_gps" (
                "code_insee" varchar(255),
                "nom_commune" varchar(255),
                "code_postal" varchar(255),
                "latitude" numeric(9,6),
                "longitude" numeric(9,6)
            );

            CREATE TABLE IF NOT EXISTS "sa_ept" (
                "etablissement_public_territorial" varchar(255),
                "commune" varchar(255),
                "departement" varchar(255),
                "code_comm" varchar(25)
            );

            CREATE TABLE IF NOT EXISTS "sa_zones_infradepartementales" (
                "code_insee" varchar(255),
                "libelle_commune" varchar(255),
                "nom_departement" text,
                "nom_region" varchar(255),
                "nom_arrondissement" varchar(255),
                "nom_zone_emploi_2020" varchar(255),
                "code_commune" varchar,
                "nom_epci" varchar(255),
                "type_epci" varchar
            );

            CREATE TABLE IF NOT EXISTS "code_rome_domaine_professionnel" (
                "grand_domaine" varchar(255),
                "domaine_professionnel" varchar(255),
                "code_rome" varchar,
                "description_code_rome" varchar,
                "date_mise_à_jour_metabase" date
            );

            CREATE TABLE IF NOT EXISTS "reseau_iae_adherents" (
                "SIRET" text,
                "Réseau IAE" text
            );

            CREATE TABLE IF NOT EXISTS "suivi_visiteurs_tb_prives" (
                "Date" timestamp,
                "Département" text,
                "Nom Département" text,
                "Tableau de bord" text,
                "Visiteurs uniques" float8,
                "Visites" float8,
                "Actions" float8,
                "Nombre maximum d'actions en une visite" float8,
                "Rebonds" float8,
                "Temps total passé par les visiteurs (en secondes)" float8,
                "Visites retour" float8,
                "Actions des visites retour" float8,
                "Visiteurs uniques de retour" float8,
                "Visiteurs connus" float8,
                "Actions maximum dans une visite de retour" float8,
                "Pourcentage de rebond pour les visites retour" text,
                "Nombre moyen d'actions par visiteur connu" float8,
                "Durée moyenne des visites pour les visiteurs connus (en second" text,
                "Temps moyen de connexion" text,
                "Moy. heure du serveur" text,
                "Conversions" float8,
                "Visites avec conversions" float8,
                "Revenu" float8,
                "Taux de conversion" text,
                "nb_conversions_returning_visit" float8,
                "nb_visits_converted_returning_visit" float8,
                "revenue_returning_visit" float8,
                "conversion_rate_returning_visit" text,
                "Vues de page" float8,
                "Vues de page uniques" float8,
                "Téléchargements" float8,
                "Téléchargements uniques" float8,
                "Liens sortants" float8,
                "Liens sortants uniques" float8,
                "Recherches" float8,
                "Taux de rebond" text,
                "Actions par visite" float8,
                "Durée moy. des visites (en secondes)" text,
                "Moy. Durée d'une nouvelle visite (en sec)" text,
                "Moy. Actions par nouvelle visite" float8,
                "Taux de rebond pour une nouvelle visite" text,
                "Nouvelle Visite" float8,
                "Actions de Nouvelles Visites" float8,
                "Nouveaux visiteurs uniques" float8,
                "Nouveaux Utilisateurs" float8,
                "max_actions_new" float8,
                "nb_conversions_new_visit" float8,
                "nb_visits_converted_new_visit" float8,
                "revenue_new_visit" float8,
                "conversion_rate_new_visit" text
            );

            CREATE TABLE IF NOT EXISTS "suivi_utilisateurs_tb_prives" (
                "id" varchar(300),
                "numero_departement" varchar(5),
                "nom_département" varchar(300),
                "région" varchar(200),
                "structure" varchar(150),
                "type_siae" varchar(50),
                "nom_siae" varchar(350),
                "nom_cd" varchar(350),
                "nom_agence_pe" varchar(350),
                "utilisateur" varchar(100)
            );

        """
        print("Creating unversioned tables if needed...")
        cur.execute(sql.SQL(create_table_sql_requests))
        conn.commit()
        print("Done.")


def populate_table(table, batch_size, querysets=None, extra_object=None):
    """
    About commits: a single final commit freezes the itou-metabase-db temporarily, making
    our GUI unable to connect to the db during this commit.

    This is why we instead do small and frequent commits, so that the db stays available
    throughout the script.

    Note that psycopg will always automatically open a new transaction when none is open.
    Thus it will open a new one after each such commit.
    """

    table_name = table.name

    total_rows = sum([queryset.count() for queryset in querysets])

    table = copy.deepcopy(table)
    # because of tenacity, we can't just add the last column to the global variable
    table.add_columns(
        [
            {
                "name": "date_mise_à_jour_metabase",
                "type": "date",
                "comment": "Date de dernière mise à jour de Metabase",
                # As metabase daily updates run typically every night after midnight, the last day with
                # complete data is yesterday, not today.
                "fn": lambda o: timezone.now() + timezone.timedelta(days=-1),
            },
        ]
    )

    # Transform boolean fields into 0-1 integer fields as
    # metabase cannot sum or average boolean columns ¯\_(ツ)_/¯
    for c in table.columns:
        if c["type"] == "boolean":
            c["type"] = "integer"
            c["fn"] = compose(convert_boolean_to_int, c["fn"])

    print(f"Injecting {total_rows} rows with {len(table.columns)} columns into table {table_name}:")

    new_table_name = get_new_table_name(table_name)
    create_table(new_table_name, [(c["name"], c["type"]) for c in table.columns], reset=True)

    with MetabaseDatabaseCursor() as (cur, conn):

        def inject_chunk(table_columns, chunk, new_table_name):
            rows = [[c["fn"](row) for c in table_columns] for row in chunk]
            with cur.copy(
                sql.SQL("COPY {new_table_name} ({fields}) FROM STDIN WITH (FORMAT BINARY)").format(
                    new_table_name=sql.Identifier(new_table_name),
                    fields=sql.SQL(",").join(
                        [sql.Identifier(c["name"]) for c in table_columns],
                    ),
                )
            ) as copy:
                copy.set_types([c["type"] for c in table_columns])
                for row in rows:
                    copy.write_row(row)
            conn.commit()

        # Add comments on table columns.
        for c in table.columns:
            assert set(c.keys()) == {"name", "type", "comment", "fn"}
            column_name = c["name"]
            column_comment = c["comment"]
            comment_query = sql.SQL("comment on column {new_table_name}.{column_name} is {column_comment}").format(
                new_table_name=sql.Identifier(new_table_name),
                column_name=sql.Identifier(column_name),
                column_comment=sql.Literal(column_comment),
            )
            cur.execute(comment_query)

        conn.commit()

        if extra_object:
            inject_chunk(table_columns=table.columns, chunk=[extra_object], new_table_name=new_table_name)

        written_rows = 0
        for queryset in querysets:
            # Insert rows by batch of batch_size.
            # A bigger number makes the script faster until a certain point,
            # but it also increases RAM usage.
            for chunk_qs in chunked_queryset(queryset, chunk_size=batch_size):
                inject_chunk(table_columns=table.columns, chunk=chunk_qs, new_table_name=new_table_name)
                written_rows += chunk_qs.count()
                print(f"count={written_rows} of total={total_rows} written")

            # Trigger garbage collection to optimize memory use.
            gc.collect()

    rename_table_atomically(new_table_name, table_name)
