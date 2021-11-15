"""
Populate metabase with fluxIAE data and some custom tables for our needs.

For itou data, see the other script `populate_metabase_itou.py`.

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
import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from itou.metabase.management.commands._dataframes import store_df
from itou.metabase.management.commands._utils import build_custom_tables
from itou.siaes.management.commands._import_siae.utils import get_fluxiae_df, get_fluxiae_referential_filenames, timeit


if settings.METABASE_SHOW_SQL_REQUESTS:
    # Unfortunately each SQL query log appears twice ¬_¬
    mylogger = logging.getLogger("django.db.backends")
    mylogger.setLevel(logging.DEBUG)
    mylogger.addHandler(logging.StreamHandler())


class Command(BaseCommand):
    """
    Populate metabase database with fluxIAE data.

    The `dry-run` mode is useful for quickly testing changes and iterating.
    It builds tables with a dry prefix added to their name, to avoid
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
            self.log("Populating metabase is not allowed in this environment.")
            return

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
        build_custom_tables(dry_run=self.dry_run)

    def handle(self, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        self.dry_run = dry_run
        self.populate_metabase_fluxiae()
        self.log("-" * 80)
        self.log("Done.")
