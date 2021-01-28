"""
Populate metabase database with transformed data from itou database.

For fluxIAE data, see the other script `populate_metabase_fluxiae.py`.

This script runs every night in production via a cronjob, but can also be run from your local dev.

This script reads data from the itou production database,
transforms it for the convenience of our metabase non tech-savvy,
french speaking only users, and injects the result into metabase.

The itou production database is never modified, only read.

The metabase database tables are trashed and recreated every time.

The data is heavily denormalized among tables so that the metabase user
has all the fields needed and thus never needs to perform joining two tables.

We maintain a google sheet with extensive documentation about all tables and fields.
Its name is "Documentation ITOU METABASE [Master doc]". No direct link here for safety reasons.
"""
import gc
import logging

import psycopg2
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from tqdm import tqdm

from itou.approvals.models import Approval, PoleEmploiApproval
from itou.job_applications.models import JobApplication
from itou.jobs.models import Rome
from itou.metabase.management.commands import _approvals, _job_applications, _job_seekers, _organizations, _siaes
from itou.metabase.management.commands._database import MetabaseDatabaseCursor
from itou.metabase.management.commands._utils import chunked_queryset, compose, convert_boolean_to_int
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae


if settings.METABASE_SHOW_SQL_REQUESTS:
    # Unfortunately each SQL query log appears twice ¬_¬
    mylogger = logging.getLogger("django.db.backends")
    mylogger.setLevel(logging.DEBUG)
    mylogger.addHandler(logging.StreamHandler())


class Command(BaseCommand):
    """
    Populate metabase database.

    The `dry-run` mode is useful for quickly testing changes and iterating.
    It builds tables with a *_dry_run suffix added to their name, to avoid
    touching any real table, and injects only a sample of data.

    To populate alternate tables with sample data:
        django-admin populate_metabase --verbosity=2 --dry-run

    When ready:
        django-admin populate_metabase --verbosity=2
    """

    help = "Populate metabase database."

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

    def commit(self):
        """
        A single final commit freezes the itou-metabase-db temporarily,
        making our GUI unable to connect to the db during this commit.

        This is why we instead do small and frequent commits, so that the db
        stays available throughout the script.
        """
        self.conn.commit()

    def cleanup_tables(self, table_name):
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_new;")
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_old;")
        self.commit()

    def inject_chunk(self, table_columns, chunk, insert_query):
        """
        Insert chunk of objects into table.
        """
        data = [[c["lambda"](o) for c in table_columns] for o in chunk]
        psycopg2.extras.execute_values(self.cur, insert_query, data, template=None)
        self.commit()

    def populate_table(self, table_name, table_columns, queryset=None, querysets=None, extra_object=None):
        """
        Generic method to populate each table.
        Create table with a temporary name, add column comments,
        inject content and finally swap with the target table.
        """
        if queryset is not None:
            assert not querysets
            querysets = [queryset]
            queryset = None

        if self.dry_run:
            table_name = f"{table_name}_dry_run"
        self.cleanup_tables(table_name)

        if self.dry_run:
            total_rows = sum(
                [min(queryset.count(), settings.METABASE_DRY_RUN_ROWS_PER_QUERYSET) for queryset in querysets]
            )
        else:
            total_rows = sum([queryset.count() for queryset in querysets])

        table_columns += [
            {
                "name": "date_mise_à_jour_metabase",
                "type": "date",
                "comment": "Date de dernière mise à jour de Metabase",
                "lambda": lambda o: timezone.now(),
            },
        ]

        # Transform boolean fields into 0-1 integer fields as
        # metabase cannot sum or average boolean columns ¯\_(ツ)_/¯
        for c in table_columns:
            if c["type"] == "boolean":
                c["type"] = "integer"
                c["lambda"] = compose(convert_boolean_to_int, c["lambda"])

        self.log(f"Injecting {total_rows} rows with {len(table_columns)} columns into table {table_name}:")

        # Create table.
        statement = ", ".join([f'{c["name"]} {c["type"]}' for c in table_columns])
        self.cur.execute(f"CREATE TABLE {table_name}_new ({statement});")
        self.commit()

        # Add comments on table columns.
        for c in table_columns:
            assert set(c.keys()) == set(["name", "type", "comment", "lambda"])
            column_name = c["name"]
            column_comment = c["comment"]
            self.cur.execute(f"comment on column {table_name}_new.{column_name} is '{column_comment}';")
        self.commit()

        # Insert rows by batch of settings.METABASE_INSERT_BATCH_SIZE.
        column_names = [f'{c["name"]}' for c in table_columns]
        statement = ", ".join(column_names)
        insert_query = f"insert into {table_name}_new ({statement}) values %s"

        if extra_object:
            # Insert extra object without counter/tqdm for simplicity.
            self.inject_chunk(table_columns=table_columns, chunk=[extra_object], insert_query=insert_query)

        with tqdm(total=total_rows) as progress_bar:
            for queryset in querysets:
                injections = 0
                total_injections = queryset.count()
                if self.dry_run:
                    total_injections = min(total_injections, settings.METABASE_DRY_RUN_ROWS_PER_QUERYSET)

                for chunk_qs in chunked_queryset(queryset, chunk_size=settings.METABASE_INSERT_BATCH_SIZE):
                    injections_left = total_injections - injections
                    if chunk_qs.count() > injections_left:
                        chunk_qs = chunk_qs[:injections_left]
                    self.inject_chunk(table_columns=table_columns, chunk=chunk_qs, insert_query=insert_query)
                    injections += chunk_qs.count()
                    progress_bar.update(chunk_qs.count())

                # Trigger garbage collection to optimize memory use.
                gc.collect()

        # Swap new and old table nicely to minimize downtime.
        self.cur.execute(f"ALTER TABLE IF EXISTS {table_name} RENAME TO {table_name}_old;")
        self.cur.execute(f"ALTER TABLE {table_name}_new RENAME TO {table_name};")
        self.commit()
        self.cur.execute(f"DROP TABLE IF EXISTS {table_name}_old;")
        self.commit()

    def populate_siaes(self):
        """
        Populate siaes table with various statistics.
        """
        queryset = (
            Siae.objects.active()
            .prefetch_related(
                "members",
                "siaemembership_set",
                "job_applications_received",
                "job_applications_received__logs",
                "job_description_through",
            )
            .all()
        )

        self.populate_table(table_name="structures", table_columns=_siaes.TABLE_COLUMNS, queryset=queryset)

    def populate_organizations(self):
        """
        Populate prescriber organizations,
        and add a special "ORG_OF_PRESCRIBERS_WITHOUT_ORG" to gather stats
        of prescriber users *without* any organization.
        """
        queryset = PrescriberOrganization.objects.prefetch_related(
            "prescribermembership_set", "members", "jobapplication_set"
        ).all()

        self.populate_table(
            table_name="organisations",
            table_columns=_organizations.TABLE_COLUMNS,
            queryset=queryset,
            extra_object=_organizations.ORG_OF_PRESCRIBERS_WITHOUT_ORG,
        )

    def populate_job_applications(self):
        """
        Populate job applications table with various statistics.
        """
        queryset = (
            JobApplication.objects.select_related("to_siae", "sender_siae", "sender_prescriber_organization")
            .prefetch_related("logs")
            .all()
        )

        self.populate_table(
            table_name="candidatures", table_columns=_job_applications.TABLE_COLUMNS, queryset=queryset
        )

    def populate_approvals(self):
        """
        Populate approvals table by merging Approvals and PoleEmploiApprovals.
        Some stats are available on both kinds of objects and some only
        on Approvals.
        We can link PoleEmploiApproval back to its PrescriberOrganization via
        the SAFIR code.
        """
        queryset1 = Approval.objects.prefetch_related(
            "user", "user__job_applications", "user__job_applications__to_siae"
        ).all()
        queryset2 = PoleEmploiApproval.objects.filter(
            start_at__gte=_approvals.POLE_EMPLOI_APPROVAL_MINIMUM_START_DATE
        ).all()

        self.populate_table(
            table_name="pass_agréments", table_columns=_approvals.TABLE_COLUMNS, querysets=[queryset1, queryset2]
        )

    def populate_job_seekers(self):
        """
        Populate job seekers table and add detailed stats about
        diagnoses and administrative criteria, including one column
        for each of the 15 possible criteria.

        Note that job seeker id is anonymized.
        """
        queryset = (
            get_user_model()
            .objects.filter(is_job_seeker=True)
            .prefetch_related(
                "eligibility_diagnoses",
                "eligibility_diagnoses__administrative_criteria",
                "eligibility_diagnoses__author_prescriber_organization",
                "eligibility_diagnoses__author_siae",
                "job_applications",
                "job_applications__to_siae",
                "socialaccount_set",
            )
            .all()
        )

        self.populate_table(table_name="candidats", table_columns=_job_seekers.TABLE_COLUMNS, queryset=queryset)

    def populate_job_romes(self):
        """
        Populate rome codes.
        """
        queryset = Rome.objects.all()

        table_columns = [
            {
                "name": "code_rome",
                "type": "varchar",
                "comment": "Code ROME",
                "lambda": lambda o: o.code,
            },
            {
                "name": "description_code_rome",
                "type": "varchar",
                "comment": "Description du code ROME",
                "lambda": lambda o: o.name,
            },
        ]

        self.populate_table(table_name="codes_rome", table_columns=table_columns, queryset=queryset)

    def populate_metabase(self):
        if not settings.ALLOW_POPULATING_METABASE:
            self.log("Populating metabase is not allowed in this environment.")
            return
        with MetabaseDatabaseCursor() as (cur, conn):
            self.cur = cur
            self.conn = conn
            self.populate_siaes()
            self.populate_organizations()
            self.populate_job_seekers()
            self.populate_job_applications()
            self.populate_approvals()
            self.populate_job_romes()

    def handle(self, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        self.dry_run = dry_run
        self.populate_metabase()
        self.log("-" * 80)
        self.log("Done.")
