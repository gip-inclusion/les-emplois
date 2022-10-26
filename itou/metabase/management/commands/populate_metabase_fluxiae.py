"""
Populate metabase with fluxIAE data and some custom tables for our needs.

For itou data, see the other script `populate_metabase_itou.py`.

This script is launched manually every week by Supportix on a fast machine, not production.

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
~1M
Contracts are stored in the ContratMission table, which is badly named and should be named Contrat instead imho.
This table contains one row per contract, its primary key is ctr_id. It has absolutely nothing to do with missions.

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

4) Relationships between models.

One structure has many contracts.

One contract has many missions.

One mission has many EMI.

An EMI does not necessarily have a mission.

"""
from django.conf import settings
from django.core.management.base import BaseCommand

from itou.metabase import constants
from itou.metabase.management.commands._dataframes import store_df
from itou.metabase.management.commands._utils import build_final_tables, enable_sql_logging

# FIXME(vperron): Those helpers are shared between populate_metabase and import_siae.
# It would make a lot more sense, to avoid eventual circular imports, to move everything
# related to the fluxiae logic in its own application. Some architecture still needs to be thought of there.
# Another way to do it would be to rationalize our import (to Itou) & export (to Metabase) logic.
from itou.siaes.management.commands._import_siae.utils import get_fluxiae_df, get_fluxiae_referential_filenames
from itou.utils.python import timeit
from itou.utils.slack import send_slack_message


if constants.METABASE_SHOW_SQL_REQUESTS:
    enable_sql_logging()


class Command(BaseCommand):
    """
    Populate metabase database with fluxIAE data.

    The `dry-run` mode is useful for quickly testing changes and iterating.
    It builds tables with a dry prefix added to their name, to avoid
    touching any real table, and injects only a sample of data.

    To populate alternate tables with sample data:
        django-admin populate_metabase_fluxiae --dry-run

    When ready:
        django-admin populate_metabase_fluxiae
    """

    help = "Populate metabase database with fluxIAE data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Populate alternate tables with sample data"
        )

    @timeit
    def populate_fluxiae_view(self, vue_name, skip_first_row=True):
        df = get_fluxiae_df(vue_name=vue_name, skip_first_row=skip_first_row, dry_run=self.dry_run)
        store_df(df=df, table_name=vue_name, dry_run=self.dry_run)

    def populate_fluxiae_referentials(self):
        for filename in get_fluxiae_referential_filenames():
            self.populate_fluxiae_view(vue_name=filename)

    @timeit
    def populate_metabase_fluxiae(self):
        if not settings.ALLOW_POPULATING_METABASE:
            self.stdout.write("Populating metabase is not allowed in this environment.")
            return

        if not self.dry_run:
            send_slack_message(
                ":rocket: Début de la mise à jour hebdomadaire de Metabase avec les dernières données FluxIAE :rocket:"
            )

        self.populate_fluxiae_referentials()

        self.populate_fluxiae_view(vue_name="fluxIAE_AnnexeFinanciere")
        self.populate_fluxiae_view(vue_name="fluxIAE_AnnexeFinanciereACI")
        self.populate_fluxiae_view(vue_name="fluxIAE_ContratMission", skip_first_row=False)
        self.populate_fluxiae_view(vue_name="fluxIAE_Encadrement")
        self.populate_fluxiae_view(vue_name="fluxIAE_EtatMensuelAgregat")
        self.populate_fluxiae_view(vue_name="fluxIAE_EtatMensuelIndiv")
        self.populate_fluxiae_view(vue_name="fluxIAE_Formations")
        self.populate_fluxiae_view(vue_name="fluxIAE_Missions")
        self.populate_fluxiae_view(vue_name="fluxIAE_MissionsEtatMensuelIndiv")
        self.populate_fluxiae_view(vue_name="fluxIAE_PMSMP")
        self.populate_fluxiae_view(vue_name="fluxIAE_Salarie", skip_first_row=False)
        self.populate_fluxiae_view(vue_name="fluxIAE_Structure")

        # Build custom tables by running raw SQL queries on existing tables.
        build_final_tables(dry_run=self.dry_run)

        if not self.dry_run:
            send_slack_message(
                ":white_check_mark: Fin de la mise à jour hebdomadaire de Metabase avec les"
                " dernières données FluxIAE :white_check_mark:"
            )

    def handle(self, dry_run=False, **options):
        self.dry_run = dry_run
        self.populate_metabase_fluxiae()
        self.stdout.write("-" * 80)
        self.stdout.write("Done.")
