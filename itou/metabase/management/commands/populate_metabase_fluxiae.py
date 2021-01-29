"""
Populate metabase with fluxIAE data and some custom tables for our needs (mainly `missions_ai_ehpad`).

For itou data, see the other script `populate_metabase.py`.

At this time this script is only supposed to run manually on your local dev, not in production.

It manipulates large dataframes in memory (~10M rows) and thus is not optimized for production low memory environment.

This script takes ~2 hours to complete.

Refactoring it for low memory use would make it even longer and is actually not trivial. It might be attempted though.

1) Vocabulary.

- aka = also known as
- sme = suivi mensuel
- dsm = détail suivi mensuel
- emi = état mensuel individuel (AFAIU same as `dsm`)
- mei = mission état (mensuel) individuel
- ctr = contrat
- mis = mission

2) Basic fluxIAE models.

Structure
~5K

Contract
No dedicated table so the total number of contracts is unknown but most likely ~1M based on other tables.

"Etat Mensuel Individuel" aka EMI aka DSM
~7M
Each month each employer inputs an EMI for each of their employees.
~20% of EMI are attached to a Mission.

Mission
~3M
Employers generally input their EMI without Mission, but sometimes, when they send their employees to another
employer, they do input a Mission attached to their EMI.

3) Advanced fluxIAE models acting as a relationship between two basic models.

Mission-EMI aka MEI
~3M
Store associations between EMI and Missions.

Contract-Mission
~1M
Store associations between Contracts and Missions.

4) Relationships between models.

One structure has many contracts.

One contract has many missions.

One mission has many EMI.

An EMI does not necessarily have a mission.

"""
import logging

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

from itou.metabase.management.commands._database_psycopg2 import MetabaseDatabaseCursor
from itou.metabase.management.commands._database_sqlalchemy import PG_ENGINE
from itou.metabase.management.commands._missions_ai_ehpad import MISSIONS_AI_EPHAD_SQL_REQUEST
from itou.siaes.management.commands._import_siae.utils import get_filename, timeit
from itou.siaes.models import Siae
from itou.utils.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS


if settings.METABASE_SHOW_SQL_REQUESTS:
    # Unfortunately each SQL query log appears twice ¬_¬
    mylogger = logging.getLogger("django.db.backends")
    mylogger.setLevel(logging.DEBUG)
    mylogger.addHandler(logging.StreamHandler())


class Command(BaseCommand):
    """
    Populate metabase database with fluxIAE data.

    The `dry-run` mode is useful for quickly testing changes and iterating.
    It builds tables with a *_dry_run suffix added to their name, to avoid
    touching any real table, and injects only a sample of data.

    To populate alternate tables with sample data:
        django-admin populate_metabase_fluxiae --verbosity=2 --dry-run

    When ready:
        django-admin populate_metabase_fluxiae --verbosity=2
    """

    help = "Populate metabase database with fluxIAE data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Populate alternate tables with sample data"
        )

    def set_logger(self, verbosity):
        """
        Set logger level based on the verbosity option.
        """
        handler = logging.StreamHandler(self.stdout)

        self.logger = logging.getLogger(__name__)
        self.logger.propagate = False
        self.logger.addHandler(handler)

        self.logger.setLevel(logging.INFO)
        if verbosity > 1:
            self.logger.setLevel(logging.DEBUG)

    def log(self, message):
        self.logger.debug(message)

    def anonymize_df(self, df):
        """
        Drop and/or anonymize sensitive data in dataframe.
        """
        if "salarie_date_naissance" in df.columns.tolist():
            df["salarie_annee_naissance"] = df.salarie_date_naissance.str[-4:].astype(int)

        deletable_columns = [
            "nom_usage",
            "nom_naissance",
            "prenom",
            "date_naissance",
            "telephone",
            "adr_mail",
            "salarie_agrement",
            "salarie_adr_point_remise",
            "salarie_adr_cplt_point_geo",
            "salarie_adr_numero_voie",
            "salarie_codeextensionvoie",
            "salarie_codetypevoie",
            "salarie_adr_libelle_voie",
            "salarie_adr_cplt_distribution",
            "salarie_adr_qpv_nom",
        ]

        for deletable_column in deletable_columns:
            for column_name in df.columns.tolist():
                if deletable_column in column_name:
                    del df[column_name]

        # Better safe than sorry when dealing with sensitive data!
        for column_name in df.columns.tolist():
            for deletable_column in deletable_columns:
                assert deletable_column not in column_name

        return df

    def get_df(self, vue_name, converters=None, description=None, skip_first_row=True):
        """
        Load fluxIAE CSV file as a dataframe.
        """
        self.log(f"Loading {vue_name} as a dataframe ...")

        filename = get_filename(
            filename_prefix=vue_name,
            filename_extension=".csv",
        )

        # Prepare parameters for pandas.read_csv method.
        kwargs = {}

        if skip_first_row:
            # Some fluxIAE exports have a leading "DEB***" row, some don't.
            kwargs["skiprows"] = 1

        if self.dry_run:
            kwargs["nrows"] = 100
        else:
            # Ignore last row. All fluxIAE exports have a final "FIN***" row.
            # Note that `skipfooter` and `nrows` are mutually exclusive.
            kwargs["skipfooter"] = 1
            # Fix warning caused by using `skipfooter`.
            kwargs["engine"] = "python"

        if converters:
            kwargs["converters"] = converters

        df = pd.read_csv(
            filename,
            sep="|",
            error_bad_lines=False,
            **kwargs,
        )

        # If there is only one column, something went wrong, let's break early.
        # Most likely an incorrect skip_first_row value.
        assert len(df.columns.tolist()) >= 2

        df = self.anonymize_df(df)

        self.log(f"Loaded {len(df)} rows for {vue_name}.")
        return df

    def store_df(self, df, vue_name):
        """
        Store dataframe in database.
        """
        if self.dry_run:
            vue_name += "_dry_run"
        df.to_sql(
            name=vue_name,
            con=PG_ENGINE,
            if_exists="replace",
            index=False,
            chunksize=1000,
            # INSERT by batch and not one by one. Increases speed x100.
            method="multi",
        )
        self.log(f"Stored {vue_name} in database ({len(df)} rows).")

    @timeit
    def populate_fluxiae_structures(self):
        """
        Populate fluxIAE_Structure table and enrich it with some itou data.
        """
        vue_name = "fluxIAE_Structure"
        df = self.get_df(
            vue_name=vue_name,
            converters={
                "structure_siret_actualise": str,
                "structure_siret_signature": str,
                "structure_adresse_mail_corresp_technique": str,
                "structure_adresse_gestion_cp": str,
                "structure_adresse_gestion_telephone": str,
            },
        )

        # Enrich Vue Structure with some itou data.
        for index, row in df.iterrows():
            asp_id = row["structure_id_siae"]
            siaes = Siae.objects.filter(source=Siae.SOURCE_ASP, convention__asp_id=asp_id).select_related("convention")

            # Preferably choose an AI.
            ai_siaes = [s for s in siaes if s.kind == Siae.KIND_AI]
            if len(ai_siaes) >= 1:
                siae = ai_siaes[0]
            else:
                siae = siaes.first()

            if siae:
                # row is a copy no longer connected to initial df.
                df.loc[index, "itou_name"] = siae.display_name
                df.loc[index, "itou_kind"] = siae.kind
                df.loc[index, "itou_post_code"] = siae.post_code
                df.loc[index, "itou_city"] = siae.city
                df.loc[index, "itou_department_code"] = siae.department
                df.loc[index, "itou_department"] = DEPARTMENTS.get(siae.department)
                df.loc[index, "itou_region"] = DEPARTMENT_TO_REGION.get(siae.department)
                df.loc[index, "itou_latitude"] = siae.latitude
                df.loc[index, "itou_longitude"] = siae.longitude

        self.store_df(df=df, vue_name=vue_name)

    @timeit
    def populate_fluxiae_view(self, vue_name, skip_first_row=True):
        df = self.get_df(vue_name=vue_name, skip_first_row=skip_first_row)
        self.store_df(df=df, vue_name=vue_name)

    def build_table(self, table_name, sql_request):
        """
        Build a new table with given sql_request.
        Minimize downtime by building a temporary table first then swap the two tables atomically.
        """
        self.cur.execute(f'DROP TABLE IF EXISTS "{table_name}_new";')
        self.cur.execute(f'CREATE TABLE "{table_name}_new" AS {sql_request};')
        self.conn.commit()
        self.cur.execute(f'ALTER TABLE IF EXISTS "{table_name}" RENAME TO "{table_name}_old";')
        self.cur.execute(f'ALTER TABLE "{table_name}_new" RENAME TO "{table_name}";')
        self.conn.commit()
        self.cur.execute(f'DROP TABLE IF EXISTS "{table_name}_old";')
        self.conn.commit()
        self.log(f"Built {table_name} table using given sql_request.")

    @timeit
    def build_update_date_table(self):
        """
        Store fluxIAE latest update date in dedicated table for convenience.
        This way we can show on metabase dashboards how fresh our data is.
        """
        if self.dry_run:
            # This table makes no sense for a dry run.
            return
        table_name = "fluxIAE_DateDerniereMiseAJour"
        sql_request = """
            select
                max(TO_DATE(emi_date_creation, 'DD/MM/YYYY')) as date_derniere_mise_a_jour
            from "fluxIAE_EtatMensuelIndiv"
        """
        self.build_table(table_name=table_name, sql_request=sql_request)

    @timeit
    def build_missions_ai_ehpad_table(self):
        """
        Build custom missions_ai_ehpad table by joining all relevant raw tables.
        """
        if self.dry_run:
            # This table makes no sense for a dry run.
            return
        table_name = "missions_ai_ehpad"
        sql_request = MISSIONS_AI_EPHAD_SQL_REQUEST
        self.build_table(table_name=table_name, sql_request=sql_request)

    @timeit
    def populate_metabase_fluxiae(self):
        if not settings.ALLOW_POPULATING_METABASE:
            self.log("Populating metabase is not allowed in this environment.")
            return

        # Specific views with specific needs.
        self.populate_fluxiae_structures()

        # Regular views with no special treatment.
        self.populate_fluxiae_view(vue_name="fluxIAE_Missions")
        self.populate_fluxiae_view(vue_name="fluxIAE_EtatMensuelIndiv")
        self.populate_fluxiae_view(vue_name="fluxIAE_MissionsEtatMensuelIndiv")
        self.populate_fluxiae_view(vue_name="fluxIAE_ContratMission", skip_first_row=False)
        self.populate_fluxiae_view(vue_name="fluxIAE_AnnexeFinanciere")
        self.populate_fluxiae_view(vue_name="fluxIAE_Salarie", skip_first_row=False)

        with MetabaseDatabaseCursor() as (cur, conn):
            self.cur = cur
            self.conn = conn
            # Build custom tables.
            self.build_update_date_table()
            self.build_missions_ai_ehpad_table()

    def handle(self, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        self.dry_run = dry_run
        self.populate_metabase_fluxiae()
        self.log("-" * 80)
        self.log("Done.")
