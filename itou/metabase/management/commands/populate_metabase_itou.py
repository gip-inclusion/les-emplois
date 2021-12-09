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
from collections import OrderedDict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.core.paginator import Paginator
from django.utils import timezone
from psycopg2 import extras as psycopg2_extras, sql
from tqdm import tqdm

from itou.approvals.models import Approval, PoleEmploiApproval
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS
from itou.job_applications.models import JobApplication
from itou.jobs.models import Rome
from itou.metabase.management.commands import (
    _approvals,
    _insee_codes,
    _job_applications,
    _job_descriptions,
    _job_seekers,
    _organizations,
    _rome_codes,
    _siaes,
)
from itou.metabase.management.commands._database_psycopg2 import MetabaseDatabaseCursor
from itou.metabase.management.commands._database_tables import (
    get_dry_table_name,
    get_new_table_name,
    get_old_table_name,
)
from itou.metabase.management.commands._dataframes import get_df_from_rows, store_df
from itou.metabase.management.commands._utils import (
    anonymize,
    build_custom_tables,
    chunked_queryset,
    compose,
    convert_boolean_to_int,
)
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae, SiaeJobDescription
from itou.users.models import User
from itou.utils.slack import send_slack_message


# Emit more verbose slack messages about every step, not just the beginning and the ending of the command.
VERBOSE_SLACK_MESSAGES = False


if settings.METABASE_SHOW_SQL_REQUESTS:
    # Unfortunately each SQL query log appears twice ¬_¬
    mylogger = logging.getLogger("django.db.backends")
    mylogger.setLevel(logging.DEBUG)
    mylogger.addHandler(logging.StreamHandler())


class Command(BaseCommand):
    """
    Populate metabase database.

    The `dry-run` mode is useful for quickly testing changes and iterating.
    It builds tables with a dry prefix added to their name, to avoid
    touching any real table, and injects only a sample of data.

    To populate alternate tables with sample data:
        django-admin populate_metabase_itou --verbosity=2 --dry-run

    When ready:
        django-admin populate_metabase_itou --verbosity=2
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
        A single final commit freezes the itou-metabase-db temporarily, making our GUI unable to connect to the db
        during this commit.

        This is why we instead do small and frequent commits, so that the db stays available throughout the script.

        Note that psycopg2 will always automatically open a new transaction when none is open. Thus it will open
        a new one after each such commit.
        """
        self.conn.commit()

    def cleanup_tables(self, table_name):
        self.cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_new_table_name(table_name))))
        self.cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_old_table_name(table_name))))
        # Dry run tables are periodically dropped by wet runs.
        self.cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(get_dry_table_name(table_name))))
        self.commit()

    def inject_chunk(self, table_columns, chunk, new_table_name):
        """
        Insert chunk of objects into table.
        """
        insert_query = sql.SQL("insert into {new_table_name} ({fields}) values %s").format(
            new_table_name=sql.Identifier(new_table_name),
            fields=sql.SQL(",").join(
                [sql.Identifier(c["name"]) for c in table_columns],
            ),
        )
        dataset = [[c["fn"](o) for c in table_columns] for o in chunk]
        psycopg2_extras.execute_values(self.cur, insert_query, dataset, template=None)
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
            table_name = get_dry_table_name(table_name)
        new_table_name = get_new_table_name(table_name)
        old_table_name = get_old_table_name(table_name)

        with MetabaseDatabaseCursor() as (cur, conn):
            self.cur = cur
            self.conn = conn

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
                    # As metabase daily updates run typically every night after midnight, the last day with
                    # complete data is yesterday, not today.
                    "fn": lambda o: timezone.now() + timezone.timedelta(days=-1),
                },
            ]

            # Transform boolean fields into 0-1 integer fields as
            # metabase cannot sum or average boolean columns ¯\_(ツ)_/¯
            for c in table_columns:
                if c["type"] == "boolean":
                    c["type"] = "integer"
                    c["fn"] = compose(convert_boolean_to_int, c["fn"])

            self.log(f"Injecting {total_rows} rows with {len(table_columns)} columns into table {table_name}:")

            # Create table.
            create_table_query = sql.SQL("CREATE TABLE {new_table_name} ({fields_with_type})").format(
                new_table_name=sql.Identifier(new_table_name),
                fields_with_type=sql.SQL(",").join(
                    [sql.SQL(" ").join([sql.Identifier(c["name"]), sql.SQL(c["type"])]) for c in table_columns]
                ),
            )
            self.cur.execute(create_table_query)

            self.commit()

            # Add comments on table columns.
            for c in table_columns:
                assert set(c.keys()) == set(["name", "type", "comment", "fn"])
                column_name = c["name"]
                column_comment = c["comment"]
                comment_query = sql.SQL("comment on column {new_table_name}.{column_name} is {column_comment}").format(
                    new_table_name=sql.Identifier(new_table_name),
                    column_name=sql.Identifier(column_name),
                    column_comment=sql.Literal(column_comment),
                )
                self.cur.execute(comment_query)

            self.commit()

            if extra_object:
                # Insert extra object without counter/tqdm for simplicity.
                self.inject_chunk(table_columns=table_columns, chunk=[extra_object], new_table_name=new_table_name)

            with tqdm(total=total_rows) as progress_bar:
                for queryset in querysets:
                    injections = 0
                    total_injections = queryset.count()
                    if self.dry_run:
                        total_injections = min(total_injections, settings.METABASE_DRY_RUN_ROWS_PER_QUERYSET)

                    # Insert rows by batch of settings.METABASE_INSERT_BATCH_SIZE.
                    for chunk_qs in chunked_queryset(queryset, chunk_size=settings.METABASE_INSERT_BATCH_SIZE):
                        injections_left = total_injections - injections
                        if chunk_qs.count() > injections_left:
                            chunk_qs = chunk_qs[:injections_left]
                        self.inject_chunk(table_columns=table_columns, chunk=chunk_qs, new_table_name=new_table_name)
                        injections += chunk_qs.count()
                        progress_bar.update(chunk_qs.count())

                    # Trigger garbage collection to optimize memory use.
                    gc.collect()

            # Swap new and old table nicely to minimize downtime.
            self.cur.execute(
                sql.SQL("ALTER TABLE IF EXISTS {} RENAME TO {}").format(
                    sql.Identifier(table_name), sql.Identifier(old_table_name)
                )
            )
            self.cur.execute(
                sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                    sql.Identifier(new_table_name), sql.Identifier(table_name)
                )
            )
            self.commit()
            self.cleanup_tables(table_name)
            self.log("")

    def populate_siaes(self):
        """
        Populate siaes table with various statistics.
        """
        queryset = (
            Siae.objects.active()
            .prefetch_related(
                "members",
                "convention",
                "siaemembership_set",
                "job_applications_received",
                "job_applications_received__logs",
                "job_description_through",
            )
            .all()
        )

        self.populate_table(table_name="structures", table_columns=_siaes.TABLE_COLUMNS, queryset=queryset)

    def populate_job_descriptions(self):
        """
        Populate job descriptions with various statistics.
        """
        queryset = (
            SiaeJobDescription.objects.select_related(
                "siae",
                "appellation__rome",
            )
            .with_job_applications_count()
            .all()
        )

        self.populate_table(
            table_name="fiches_de_poste", table_columns=_job_descriptions.TABLE_COLUMNS, queryset=queryset
        )

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
            .filter(created_from_pe_approval=False)
            .all()
        )

        self.populate_table(
            table_name="candidatures", table_columns=_job_applications.TABLE_COLUMNS, queryset=queryset
        )

    def populate_selected_jobs(self):
        """
        Populate associations between job applications and job descriptions.
        """
        table_name = "fiches_de_poste_par_candidature"
        chunk_size = 1000
        self.log(f"Preparing content for {table_name} table by chunk of {chunk_size} items...")

        # Iterating directly on this very large queryset results in psycopg2.errors.DiskFull error.
        # We use pagination to mitigate this issue.
        queryset = JobApplication.objects.prefetch_related("selected_jobs").all()
        paginator = Paginator(queryset, chunk_size)

        rows = []
        for page_idx in tqdm(range(1, paginator.num_pages + 1)):
            for ja in paginator.page(page_idx).object_list:
                for jd in ja.selected_jobs.all():
                    # We want to preserve the order of columns.
                    row = OrderedDict()

                    row["id_fiche_de_poste"] = jd.pk
                    row["id_anonymisé_candidature"] = anonymize(
                        ja.pk, salt=_job_applications.JOB_APPLICATION_PK_ANONYMIZATION_SALT
                    )

                    rows.append(row)
            if self.dry_run and len(rows) >= 1000:
                break

        df = get_df_from_rows(rows)
        store_df(df=df, table_name=table_name, dry_run=self.dry_run)

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
            User.objects.filter(is_job_seeker=True)
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

    def populate_rome_codes(self):
        queryset = Rome.objects.all()

        self.populate_table(table_name="codes_rome", table_columns=_rome_codes.TABLE_COLUMNS, queryset=queryset)

    def populate_insee_codes(self):
        queryset = City.objects.all()

        self.populate_table(table_name="communes", table_columns=_insee_codes.TABLE_COLUMNS, queryset=queryset)

    def populate_departments(self):
        """
        Populate department codes, department names and region names.
        """
        table_name = "departements"
        self.log(f"Preparing content for {table_name} table...")

        rows = []
        for dpt_code, dpt_name in tqdm(DEPARTMENTS.items()):
            # We want to preserve the order of columns.
            row = OrderedDict()

            row["code_departement"] = dpt_code
            row["nom_departement"] = dpt_name
            row["nom_region"] = DEPARTMENT_TO_REGION[dpt_code]

            rows.append(row)

        df = get_df_from_rows(rows)
        store_df(df=df, table_name=table_name, dry_run=self.dry_run)

    def report_data_inconsistencies(self):
        """
        Report data inconsistencies that were previously ignored during `populate_approvals` method in order to avoid
        having the script break in the middle. This way, the scripts breaks only at the end with informative
        fatal errors after having completed its job.
        """
        fatal_errors = 0
        self.log("Checking data for inconsistencies.")
        for approval in Approval.objects.prefetch_related("user").all():
            user = approval.user
            if not user.is_job_seeker:
                self.log(f"FATAL ERROR: user {user.id} has an approval but is not a job seeker")
                fatal_errors += 1

        if fatal_errors >= 1:
            raise RuntimeError(
                "The command completed all its actions successfully but at least one fatal error needs "
                "manual resolution, see command output"
            )

    def build_custom_tables(self):
        build_custom_tables(dry_run=self.dry_run)

    def populate_metabase_itou(self):
        if not settings.ALLOW_POPULATING_METABASE:
            self.log("Populating metabase is not allowed in this environment.")
            return

        send_slack_message(
            ":rocket: Début de la mise à jour quotidienne de Metabase avec les dernières données C1 :rocket:"
        )

        updates = [
            self.populate_siaes,
            self.populate_job_descriptions,
            self.populate_organizations,
            self.populate_job_seekers,
            self.populate_job_applications,
            self.populate_selected_jobs,
            self.populate_approvals,
            self.populate_rome_codes,
            self.populate_insee_codes,
            self.populate_departments,
            self.build_custom_tables,
            self.report_data_inconsistencies,
        ]

        for update in updates:
            if VERBOSE_SLACK_MESSAGES:
                send_slack_message(f"Début de l'étape {update.__name__} :rocket:")
            update()
            if VERBOSE_SLACK_MESSAGES:
                send_slack_message(f"Fin de l'étape {update.__name__} :white_check_mark:")

        send_slack_message(
            ":rocket: Fin de la mise à jour quotidienne de Metabase avec les dernières données C1 :rocket:"
        )

    def handle(self, dry_run=False, **options):
        self.set_logger(options.get("verbosity"))
        self.dry_run = dry_run
        self.populate_metabase_itou()
        self.log("-" * 80)
        self.log("Done.")
