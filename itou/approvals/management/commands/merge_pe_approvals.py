from django.core.management.base import BaseCommand
from django.db import connection
from psycopg2 import sql  # noqa
from tqdm import tqdm

from itou.approvals.models import PoleEmploiApproval


class Command(BaseCommand):
    """
    ./manage.py merge_pe_approvals --reset
    """

    merge_table = "merged_approvals_poleemploiapproval"

    def add_arguments(self, parser):
        parser.add_argument("--reset", dest="reset", action="store_true", help="Resets the tables")
        parser.add_argument(
            "--dry-run", dest="dry_run", action="store_true", help="Only print possible errors and stats"
        )

    def create_new_merged_approval(self, number, matching_approvals):
        # we create another approval, based on the aggregate data.
        # We perform the migration on a duplicated table, and when an update is performed,
        # we set the 'merged' flag to true
        #
        if matching_approvals is not None and len(matching_approvals) > 0:
            # We need to find the exact duration:
            # - the oldest start date
            # - the most recent end date
            # - if we have a suspension during covid lockdown, we need to add 3 months
            pe_approval = PoleEmploiApproval()
            pe_approval.start_at = min([a.start_at for a in matching_approvals])
            pe_approval.end_at = max([a.end_at for a in matching_approvals])
            if pe_approval.overlaps_covid_lockdown:
                pe_approval.end_at = pe_approval.get_extended_covid_end_at(pe_approval.end_at)

            # and we can copy all the other data we have during the SQL insert
            approval = matching_approvals.first()

            if not self.dry_run:
                # we can bulk-update all the initial approvals
                matching_approvals.update(merged=True)
                # and insert a row in the merge table
                query = f"""INSERT INTO {self.merge_table}
                (
                    number,
                    pe_structure_code,
                    pole_emploi_id,
                    first_name,
                    last_name,
                    birth_name,
                    birthdate,
                    nir,
                    ntt_nia,
                    created_at,
                    start_at,
                    end_at,
                    merged)
                VALUES(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    true
                )"""
                values = [
                    number,
                    approval.pe_structure_code,
                    approval.pole_emploi_id,
                    approval.first_name,
                    approval.last_name,
                    approval.birth_name,
                    approval.birthdate,
                    approval.nir,
                    approval.ntt_nia,
                    pe_approval.created_at,
                    pe_approval.start_at,
                    pe_approval.end_at,
                ]
                self.cursor.execute(query, values)
                connection.commit()

    def get_count_non_merged_approvals(self):
        nb_non_merged_peapproval_sql = (
            "select count(distinct(left(number, 12))) from approvals_poleemploiapproval where merged=false"
        )

        self.cursor.execute(nb_non_merged_peapproval_sql)
        row = self.cursor.fetchone()
        return row[0]

    def get_non_merged_approvals_number12(self):
        """
        Returns the list of all the 12-digit PoleEmploiApproval number that have not yet been merged
        """
        nb_non_merged_peapproval_sql = (
            "select distinct(left(number, 12)) from approvals_poleemploiapproval where merged=false"
        )

        self.cursor.execute(nb_non_merged_peapproval_sql)
        rows = self.cursor.fetchall()
        return rows

    def reset_tables(self, reset):
        create_query = (
            f"CREATE TABLE IF NOT EXISTS {self.merge_table} (LIKE approvals_poleemploiapproval INCLUDING ALL);"  # noqa
        )
        self.cursor.execute(create_query)
        reset_queries = [
            f"TRUNCATE {self.merge_table};",  # noqa
            "UPDATE approvals_poleemploiapproval set merged=false where merged=true;",
        ]
        if reset:
            for query in reset_queries:
                print(f"Running:\n{query}")
                self.cursor.execute(query)

    def handle(self, dry_run=False, reset=False, **options):
        self.dry_run = dry_run
        self.stdout.write("Merging approvals / PASS IAE")
        self.cursor = connection.cursor()

        self.reset_tables(reset)

        pbar = tqdm(total=self.get_count_non_merged_approvals())
        print("Merge all the approvals \\o/")
        for number in self.get_non_merged_approvals_number12():
            matching_approvals = PoleEmploiApproval.objects.filter(number__startswith=number[0])  # noqa
            self.create_new_merged_approval(number[0], matching_approvals)
            pbar.update(1)
        pbar.close()
