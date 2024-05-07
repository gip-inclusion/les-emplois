"""
Populate metabase with fluxIAE data and some custom tables for our needs.

For itou data, see the other script `populate_metabase_emplois.py`.

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

# FIXME(vperron): Those helpers are shared between populate_metabase and import_siae.
# It would make a lot more sense, to avoid eventual circular imports, to move everything
# related to the fluxiae logic in its own application. Some architecture still needs to be thought of there.
# Another way to do it would be to rationalize our import (to Itou) & export (to Metabase) logic.
from itou.companies.management.commands._import_siae.utils import get_fluxiae_df, get_fluxiae_referential_filenames
from itou.metabase.dataframes import store_df
from itou.metabase.db import build_dbt_weekly
from itou.utils.command import BaseCommand
from itou.utils.python import timeit
from itou.utils.slack import send_slack_message


class Command(BaseCommand):
    help = "Populate metabase database with fluxIAE data."

    @timeit
    def populate_fluxiae_view(self, vue_name, skip_first_row=True):
        df = get_fluxiae_df(vue_name=vue_name, skip_first_row=skip_first_row)
        store_df(df=df, table_name=vue_name)

    def populate_fluxiae_referentials(self):
        for filename in get_fluxiae_referential_filenames():
            self.populate_fluxiae_view(vue_name=filename)

    @timeit
    def populate_metabase_fluxiae(self):
        send_slack_message(
            ":rocket: Début de la mise à jour hebdomadaire de Metabase avec les dernières données FluxIAE :rocket:"
        )

        self.populate_fluxiae_referentials()

        self.populate_fluxiae_view(vue_name="fluxIAE_AnnexeFinanciere")
        self.populate_fluxiae_view(vue_name="fluxIAE_AnnexeFinanciereACI")
        self.populate_fluxiae_view(vue_name="fluxIAE_Convention")
        self.populate_fluxiae_view(vue_name="fluxIAE_ContratMission")
        self.populate_fluxiae_view(vue_name="fluxIAE_Encadrement")
        self.populate_fluxiae_view(vue_name="fluxIAE_EtatMensuelAgregat")
        self.populate_fluxiae_view(vue_name="fluxIAE_EtatMensuelIndiv")
        self.populate_fluxiae_view(vue_name="fluxIAE_Financement")
        self.populate_fluxiae_view(vue_name="fluxIAE_Formations")
        self.populate_fluxiae_view(vue_name="fluxIAE_Missions")
        self.populate_fluxiae_view(vue_name="fluxIAE_MissionsEtatMensuelIndiv")
        self.populate_fluxiae_view(vue_name="fluxIAE_PMSMP")
        self.populate_fluxiae_view(vue_name="fluxIAE_Salarie")
        self.populate_fluxiae_view(vue_name="fluxIAE_Structure")

        build_dbt_weekly()

        send_slack_message(
            ":white_check_mark: Fin de la mise à jour hebdomadaire de Metabase avec les"
            " dernières données FluxIAE :white_check_mark:"
        )

    def handle(self, **options):
        self.populate_metabase_fluxiae()
