from django.db import connection
from tqdm import tqdm

from itou.approvals.models import MergedPoleEmploiApproval, PoleEmploiApproval
from itou.utils.command import BaseCommand


class Command(BaseCommand):
    """
    This command merges Pole Emploi approvals for a given PoleEmploiApproval number:
     - For every Pole Emploi appraval number:
        - it searches all the approvals that have the same number
        - it creates a new entry in MergedPoleEmploiApproval using those duplicate data. See create_new_merged_approval
    ./manage.py merge_pe_approvals --reset
    """

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
            pe_approval = PoleEmploiApproval()
            pe_approval.start_at = min([a.start_at for a in matching_approvals])
            pe_approval.end_at = max([a.end_at for a in matching_approvals])

            # and we can copy all the other data we have during the SQL insert
            approval = matching_approvals.first()

            if not self.dry_run:
                # we can bulk-update all the initial approvals
                matching_approvals.update(merged=True)
                # and insert a row in the merge table
                merged_approval = MergedPoleEmploiApproval(
                    number=number,
                    pe_structure_code=approval.pe_structure_code,
                    pole_emploi_id=approval.pole_emploi_id,
                    first_name=approval.first_name,
                    last_name=approval.last_name,
                    birth_name=approval.birth_name,
                    birthdate=approval.birthdate,
                    nir=approval.nir,
                    ntt_nia=approval.ntt_nia,
                    created_at=pe_approval.created_at,
                    start_at=pe_approval.start_at,
                    end_at=pe_approval.end_at,
                )
                merged_approval.save()
                self.stdout.write(f"merging approvals number={number}")

    def get_count_non_merged_approvals(self):
        nb_non_merged_peapproval_sql = (
            f"select count(distinct(left(number, 12))) from {PoleEmploiApproval._meta.db_table} where merged=false"
        )

        self.cursor.execute(nb_non_merged_peapproval_sql)
        row = self.cursor.fetchone()
        return row[0]

    def get_non_merged_approvals_number12(self):
        """
        Returns the list of all the 12-digit PoleEmploiApproval number that have not yet been merged
        """
        nb_non_merged_peapproval_sql = (
            f"select distinct(left(number, 12)) from {PoleEmploiApproval._meta.db_table} where merged=false"
        )

        self.cursor.execute(nb_non_merged_peapproval_sql)
        rows = self.cursor.fetchall()
        return rows

    def reset_tables(self):
        reset_queries = [
            f"TRUNCATE {MergedPoleEmploiApproval._meta.db_table};",
            f"UPDATE {PoleEmploiApproval._meta.db_table} set merged=false where merged=true;",
        ]
        for query in reset_queries:
            print(f"Running:\n{query}")
            self.cursor.execute(query)

    def handle(self, *, dry_run, reset, **options):
        self.dry_run = dry_run
        self.stdout.write("Merging approvals / PASS IAE")
        self.cursor = connection.cursor()

        if reset:
            self.reset_tables()

        progress_bar = tqdm(total=self.get_count_non_merged_approvals())
        print("Merge all the approvals \\o/")
        for number in self.get_non_merged_approvals_number12():
            matching_approvals = PoleEmploiApproval.objects.filter(number__startswith=number[0])  # noqa
            self.create_new_merged_approval(number[0], matching_approvals)
            progress_bar.update(1)
        progress_bar.close()
