"""
Populate metabase database with transformed data from itou database.

For fluxIAE data, see the other script `populate_metabase_fluxiae.py`.

This script is launched by a github action every night on a fast machine, not production.

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
from collections import OrderedDict

import tenacity
from django.core.management.base import BaseCommand
from django.db.models import Count, Max, Min, Q
from django.utils import timezone
from psycopg2 import extras as psycopg2_extras, sql

from itou.approvals.models import Approval, PoleEmploiApproval
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS
from itou.job_applications.enums import SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.jobs.models import Rome
from itou.metabase.dataframes import get_df_from_rows, store_df
from itou.metabase.db import (
    MetabaseDatabaseCursor,
    build_final_tables,
    create_table,
    get_new_table_name,
    get_old_table_name,
)
from itou.metabase.tables import (
    approvals,
    insee_codes,
    job_applications,
    job_descriptions,
    job_seekers,
    organizations,
    rome_codes,
    selected_jobs,
    siaes,
)
from itou.metabase.tables.utils import get_active_siae_pks
from itou.metabase.utils import chunked_queryset, compose, convert_boolean_to_int
from itou.prescribers.models import PrescriberOrganization
from itou.siaes.models import Siae, SiaeJobDescription
from itou.users.models import User
from itou.utils.python import timeit


def log_retry_attempt(retry_state):
    print(f"attempt failed with outcome={retry_state.outcome}")


class Command(BaseCommand):

    help = "Populate metabase database."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.MODE_TO_OPERATION = {
            "siaes": self.populate_siaes,
            "job_descriptions": self.populate_job_descriptions,
            "organizations": self.populate_organizations,
            "job_seekers": self.populate_job_seekers,
            "job_applications": self.populate_job_applications,
            "selected_jobs": self.populate_selected_jobs,
            "approvals": self.populate_approvals,
            "rome_codes": self.populate_rome_codes,
            "insee_codes": self.populate_insee_codes,
            "departments": self.populate_departments,
            "final_tables": self.build_final_tables,
            "data_inconsistencies": self.report_data_inconsistencies,
        }

    def add_arguments(self, parser):
        parser.add_argument("--mode", action="store", dest="mode", type=str, choices=self.MODE_TO_OPERATION.keys())

    def populate_table(self, table, batch_size, querysets=None, extra_object=None):
        """
        About commits: a single final commit freezes the itou-metabase-db temporarily, making
        our GUI unable to connect to the db during this commit.

        This is why we instead do small and frequent commits, so that the db stays available
        throughout the script.

        Note that psycopg2 will always automatically open a new transaction when none is open.
        Thus it will open a new one after each such commit.
        """

        table_name = table.name
        new_table_name = get_new_table_name(table_name)
        old_table_name = get_old_table_name(table_name)

        def drop_old_and_new_tables():
            with MetabaseDatabaseCursor() as (cur, conn):
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(new_table_name)))
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(sql.Identifier(old_table_name)))
                conn.commit()

        drop_old_and_new_tables()

        total_rows = sum([queryset.count() for queryset in querysets])

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

        self.stdout.write(f"Injecting {total_rows} rows with {len(table.columns)} columns into table {table_name}:")

        create_table(new_table_name, [(c["name"], c["type"]) for c in table.columns])

        with MetabaseDatabaseCursor() as (cur, conn):

            def inject_chunk(table_columns, chunk, new_table_name):
                insert_query = sql.SQL("insert into {new_table_name} ({fields}) values %s").format(
                    new_table_name=sql.Identifier(new_table_name),
                    fields=sql.SQL(",").join(
                        [sql.Identifier(c["name"]) for c in table_columns],
                    ),
                )
                dataset = [[c["fn"](o) for c in table_columns] for o in chunk]
                psycopg2_extras.execute_values(cur, insert_query, dataset, template=None)
                conn.commit()

            # Add comments on table columns.
            for c in table.columns:
                assert set(c.keys()) == set(["name", "type", "comment", "fn"])
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
                    self.stdout.write(f"count={written_rows} of total={total_rows} written")

                # Trigger garbage collection to optimize memory use.
                gc.collect()

            # Swap new and old table nicely to minimize downtime.
            cur.execute(
                sql.SQL("ALTER TABLE IF EXISTS {} RENAME TO {}").format(
                    sql.Identifier(table_name), sql.Identifier(old_table_name)
                )
            )
            cur.execute(
                sql.SQL("ALTER TABLE {} RENAME TO {}").format(
                    sql.Identifier(new_table_name), sql.Identifier(table_name)
                )
            )
            conn.commit()

        drop_old_and_new_tables()

    def populate_siaes(self):
        ONE_MONTH_AGO = timezone.now() - timezone.timedelta(days=30)
        queryset = (
            Siae.objects.active()
            .select_related("convention")
            .prefetch_related("convention__siaes", "job_description_through", "members")
            .annotate(
                last_job_application_transition_date=Max(
                    "job_applications_received__logs__timestamp",
                    filter=~Q(job_applications_received__logs__to_state=JobApplicationWorkflow.STATE_OBSOLETE),
                ),
                first_membership_join_date=Min(
                    "siaemembership__joined_at",
                ),
                total_candidatures=Count(
                    "job_applications_received",
                    distinct=True,
                ),
                total_embauches=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__state=JobApplicationWorkflow.STATE_ACCEPTED),
                    distinct=True,
                ),
                total_candidatures_30j=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__created_at__gte=ONE_MONTH_AGO),
                    distinct=True,
                ),
                total_embauches_30j=Count(
                    "job_applications_received",
                    filter=Q(
                        job_applications_received__state=JobApplicationWorkflow.STATE_ACCEPTED,
                        job_applications_received__created_at__gte=ONE_MONTH_AGO,
                    ),
                    distinct=True,
                ),
                total_auto_prescriptions=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__sender_kind=SenderKind.SIAE_STAFF),
                    distinct=True,
                ),
                total_candidatures_autonomes=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__sender_kind=SenderKind.JOB_SEEKER),
                    distinct=True,
                ),
                total_candidatures_prescripteur=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__sender_kind=SenderKind.PRESCRIBER),
                    distinct=True,
                ),
                total_candidatures_non_traitees=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__state=JobApplicationWorkflow.STATE_NEW),
                    distinct=True,
                ),
                total_candidatures_en_cours=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__state=JobApplicationWorkflow.STATE_PROCESSING),
                    distinct=True,
                ),
                # Don't try counting members or getting first join date, It's way too long
            )
            .all()
        )

        self.populate_table(siaes.TABLE, batch_size=100, querysets=[queryset])

    def populate_job_descriptions(self):
        queryset = (
            SiaeJobDescription.objects.select_related(
                "siae",
                "appellation__rome",
            )
            .filter(siae_id__in=get_active_siae_pks())
            .with_job_applications_count()
            .all()
        )

        self.populate_table(job_descriptions.TABLE, batch_size=10_000, querysets=[queryset])

    def populate_organizations(self):
        """
        Populate prescriber organizations,
        and add a special "ORG_OF_PRESCRIBERS_WITHOUT_ORG" to gather stats
        of prescriber users *without* any organization.
        """
        active_user_created_job_applications_filter = Q(
            jobapplication__created_from_pe_approval=False,
            jobapplication__to_siae_id__in=get_active_siae_pks(),
        )
        job_applications_count = Count(
            "jobapplication",
            filter=active_user_created_job_applications_filter,
            # This distinct isn't required since we don't filter on ManyToMany fields, or reverse ForeignKeys.
            # However, it' better to keep it in case someone adds such a filter.
            # We will be able to remove it when we have some tests on this function.
            distinct=True,
        )
        accepted_job_applications_count = Count(
            "jobapplication",
            filter=(
                active_user_created_job_applications_filter
                & Q(jobapplication__state=JobApplicationWorkflow.STATE_ACCEPTED)
            ),
            # This distinct isn't required since we don't filter on ManyToMany fields, or reverse ForeignKeys.
            # However, it' better to keep it in case someone adds such a filter.
            # We will be able to remove it when we have some tests on this function.
            distinct=True,
        )
        last_job_application_creation_date = Max(
            "jobapplication__created_at",
            filter=active_user_created_job_applications_filter,
        )
        queryset = (
            PrescriberOrganization.objects.prefetch_related("prescribermembership_set", "members")
            .annotate(
                job_applications_count=job_applications_count,
                accepted_job_applications_count=accepted_job_applications_count,
                last_job_application_creation_date=last_job_application_creation_date,
                # Don't try counting members or getting first join date, It's way too long
            )
            .all()
        )

        self.populate_table(
            organizations.TABLE,
            batch_size=100,
            querysets=[queryset],
            extra_object=organizations.ORG_OF_PRESCRIBERS_WITHOUT_ORG,
        )

    def populate_job_applications(self):
        queryset = (
            JobApplication.objects.select_related("to_siae", "sender", "sender_siae", "sender_prescriber_organization")
            .prefetch_related("logs")
            .only(
                "pk",
                "created_at",
                "sender_kind",
                "sender_siae__kind",
                "sender_prescriber_organization__kind",
                "sender_prescriber_organization__name",
                "sender_prescriber_organization__code_safir_pole_emploi",
                "sender_prescriber_organization__is_authorized",
                "sender__last_name",
                "sender__first_name",
                "state",
                "refusal_reason",
                "job_seeker_id",
                "to_siae__kind",
                "to_siae__brand",
                "to_siae__name",
                "to_siae__department",
                "approval_id",
                "approval_delivery_mode",
            )
            .filter(created_from_pe_approval=False, to_siae_id__in=get_active_siae_pks())
            .all()
        )

        self.populate_table(job_applications.TABLE, batch_size=1000, querysets=[queryset])

    def populate_selected_jobs(self):
        """
        Populate associations between job applications and job descriptions.
        """
        queryset = (
            JobApplication.objects.filter(created_from_pe_approval=False, to_siae_id__in=get_active_siae_pks())
            .exclude(selected_jobs=None)
            .values("pk", "selected_jobs__id")
        )

        self.populate_table(selected_jobs.TABLE, batch_size=10_000, querysets=[queryset])

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
            start_at__gte=approvals.POLE_EMPLOI_APPROVAL_MINIMUM_START_DATE
        ).all()

        self.populate_table(approvals.TABLE, batch_size=1000, querysets=[queryset1, queryset2])

    def populate_job_seekers(self):
        """
        Populate job seekers table and add detailed stats about
        diagnoses and administrative criteria, including one column
        for each of the 15 possible criteria.
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
                "created_by",
            )
            .all()
        )

        self.populate_table(job_seekers.TABLE, batch_size=1000, querysets=[queryset])

    def populate_rome_codes(self):
        queryset = Rome.objects.all()

        self.populate_table(rome_codes.TABLE, batch_size=1000, querysets=[queryset])

    def populate_insee_codes(self):
        queryset = City.objects.all()

        self.populate_table(insee_codes.TABLE, batch_size=1000, querysets=[queryset])

    def populate_departments(self):
        table_name = "departements"
        self.stdout.write(f"Preparing content for {table_name} table...")

        rows = []
        for dpt_code, dpt_name in DEPARTMENTS.items():
            # We want to preserve the order of columns.
            row = OrderedDict()

            row["code_departement"] = dpt_code
            row["nom_departement"] = dpt_name
            row["nom_region"] = DEPARTMENT_TO_REGION[dpt_code]

            rows.append(row)

        df = get_df_from_rows(rows)
        store_df(df=df, table_name=table_name)

    @timeit
    def report_data_inconsistencies(self):
        """
        Report data inconsistencies that were previously ignored during `populate_approvals` method in order to avoid
        having the script break in the middle. This way, the scripts breaks only at the end with informative
        fatal errors after having completed its job.
        """
        fatal_errors = 0
        self.stdout.write("Checking data for inconsistencies.")
        for approval in Approval.objects.prefetch_related("user").all():
            user = approval.user
            if not user.is_job_seeker:
                self.stdout.write(f"FATAL ERROR: user {user.id} has an approval but is not a job seeker")
                fatal_errors += 1

        if fatal_errors >= 1:
            raise RuntimeError(
                "The command completed all its actions successfully but at least one fatal error needs "
                "manual resolution, see command output"
            )

    @timeit
    def build_final_tables(self):
        build_final_tables()

    @timeit
    @tenacity.retry(stop=tenacity.stop_after_attempt(3), wait=tenacity.wait_fixed(5), after=log_retry_attempt)
    def handle(self, mode, **options):
        self.MODE_TO_OPERATION[mode]()
