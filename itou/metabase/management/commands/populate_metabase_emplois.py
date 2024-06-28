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

from collections import OrderedDict

import tenacity
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Count, F, Max, Min, Prefetch, Q
from django.utils import timezone
from sentry_sdk.crons import monitor

from itou.analytics.models import Datum, StatsDashboardVisit
from itou.approvals.models import Approval, PoleEmploiApproval, Prolongation, ProlongationRequest
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS
from itou.companies.enums import ContractType
from itou.companies.models import Company, CompanyMembership, JobDescription
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis
from itou.institutions.models import Institution, InstitutionMembership
from itou.job_applications.enums import JobApplicationState, Origin, RefusalReason, SenderKind
from itou.job_applications.models import JobApplication
from itou.jobs.models import Rome
from itou.metabase.dataframes import get_df_from_rows, store_df
from itou.metabase.db import build_dbt_daily, populate_table
from itou.metabase.tables import (
    analytics,
    approvals,
    companies,
    criteria,
    evaluated_criteria,
    evaluated_job_applications,
    evaluated_siaes,
    evaluation_campaigns,
    insee_codes,
    institutions,
    job_applications,
    job_descriptions,
    job_seekers,
    memberships,
    organizations,
    prolongation_requests,
    prolongations,
    rome_codes,
    selected_jobs,
    users,
)
from itou.metabase.tables.utils import get_active_companies_pks
from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.siae_evaluations.models import (
    EvaluatedAdministrativeCriteria,
    EvaluatedJobApplication,
    EvaluatedSiae,
    EvaluationCampaign,
)
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.command import BaseCommand
from itou.utils.python import timeit


def log_retry_attempt(retry_state):
    print(f"attempt failed with outcome={retry_state.outcome}")


class Command(BaseCommand):
    help = "Populate metabase database."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.MODE_TO_OPERATION = {
            "analytics": self.populate_analytics,
            "siaes": self.populate_companies,
            "job_descriptions": self.populate_job_descriptions,
            "organizations": self.populate_organizations,
            "job_seekers": self.populate_job_seekers,
            "criteria": self.populate_criteria,
            "job_applications": self.populate_job_applications,
            "selected_jobs": self.populate_selected_jobs,
            "approvals": self.populate_approvals,
            "prolongations": self.populate_prolongations,
            "prolongation_requests": self.populate_prolongation_requests,
            "institutions": self.populate_institutions,
            "evaluation_campaigns": self.populate_evaluation_campaigns,
            "evaluated_siaes": self.populate_evaluated_siaes,
            "evaluated_job_applications": self.populate_evaluated_job_applications,
            "evaluated_criteria": self.populate_evaluated_criteria,
            "users": self.populate_users,
            "memberships": self.populate_memberships,
            "rome_codes": self.populate_rome_codes,
            "insee_codes": self.populate_insee_codes,
            "insee_codes_vs_post_codes": self.populate_insee_codes_vs_post_codes,
            "departments": self.populate_departments,
            "enums": self.populate_enums,
            "dbt_daily": self.build_dbt_daily,
            "data_inconsistencies": self.report_data_inconsistencies,
        }

    def add_arguments(self, parser):
        parser.add_argument("--mode", action="store", dest="mode", type=str, choices=self.MODE_TO_OPERATION.keys())

    def populate_analytics(self):
        populate_table(analytics.AnalyticsTable, batch_size=10_000, querysets=[Datum.objects.all()])
        populate_table(analytics.DashboardVisitTable, batch_size=10_000, querysets=[StatsDashboardVisit.objects.all()])

    def populate_companies(self):
        ONE_MONTH_AGO = timezone.now() - timezone.timedelta(days=30)
        queryset = (
            Company.objects.active()
            .select_related("convention")
            .prefetch_related("convention__siaes", "job_description_through", "members")
            .annotate(
                last_job_application_transition_date=Max(
                    "job_applications_received__logs__timestamp",
                    filter=~Q(job_applications_received__logs__to_state=JobApplicationState.OBSOLETE),
                ),
                first_membership_join_date=Min(
                    "companymembership__joined_at",
                ),
                total_candidatures=Count(
                    "job_applications_received",
                    distinct=True,
                ),
                total_embauches=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__state=JobApplicationState.ACCEPTED),
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
                        job_applications_received__state=JobApplicationState.ACCEPTED,
                        job_applications_received__created_at__gte=ONE_MONTH_AGO,
                    ),
                    distinct=True,
                ),
                total_auto_prescriptions=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__sender_company=F("job_applications_received__to_company")),
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
                total_candidatures_employeur=Count(
                    "job_applications_received",
                    filter=Q(
                        ~Q(job_applications_received__sender_company=F("job_applications_received__to_company")),
                        job_applications_received__sender_kind=SenderKind.EMPLOYER,
                    ),
                    distinct=True,
                ),
                total_candidatures_non_traitees=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__state=JobApplicationState.NEW),
                    distinct=True,
                ),
                total_candidatures_en_cours=Count(
                    "job_applications_received",
                    filter=Q(job_applications_received__state=JobApplicationState.PROCESSING),
                    distinct=True,
                ),
                # Don't try counting members or getting first join date, It's way too long
            )
            .all()
        )

        populate_table(companies.TABLE, batch_size=100, querysets=[queryset])

    def populate_job_descriptions(self):
        queryset = (
            JobDescription.objects.select_related(
                "company",
                "appellation__rome",
            )
            .filter(company_id__in=get_active_companies_pks())
            .with_job_applications_count()
            .all()
        )
        populate_table(job_descriptions.TABLE, batch_size=10_000, querysets=[queryset])

    def populate_organizations(self):
        """
        Populate prescriber organizations,
        and add a special "ORG_OF_PRESCRIBERS_WITHOUT_ORG" to gather stats
        of prescriber users *without* any organization.
        """
        active_user_created_job_applications_filter = Q(
            ~Q(jobapplication__origin=Origin.PE_APPROVAL)
            & Q(jobapplication__to_company_id__in=get_active_companies_pks())
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
                active_user_created_job_applications_filter & Q(jobapplication__state=JobApplicationState.ACCEPTED)
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

        populate_table(
            organizations.TABLE,
            batch_size=100,
            querysets=[queryset],
            extra_object=organizations.ORG_OF_PRESCRIBERS_WITHOUT_ORG,
        )

    def populate_job_seekers(self):
        """
        Populate job seekers table and add detailed stats about
        diagnoses and administrative criteria, including one column
        for each of the 15 possible criteria.
        """
        queryset = (
            User.objects.filter(kind=UserKind.JOB_SEEKER)
            .select_related("jobseeker_profile")
            .prefetch_related(
                Prefetch(
                    "eligibility_diagnoses",
                    queryset=(
                        EligibilityDiagnosis.objects.select_related(
                            "author_prescriber_organization",
                            "author_siae",
                        )
                        .annotate(
                            level_1_count=Count(
                                "administrative_criteria",
                                filter=Q(administrative_criteria__level=AdministrativeCriteriaLevel.LEVEL_1),
                            ),
                            level_2_count=Count(
                                "administrative_criteria",
                                filter=Q(administrative_criteria__level=AdministrativeCriteriaLevel.LEVEL_2),
                            ),
                            criteria_ids=ArrayAgg("administrative_criteria__pk"),
                        )
                        .order_by("-created_at")[:1]
                    ),
                    to_attr="last_eligibility_diagnosis",
                ),
                Prefetch(
                    "job_applications",
                    queryset=JobApplication.objects.select_related("to_company"),
                ),
                "created_by",
            )
            .annotate(
                eligibility_diagnoses_count=Count("eligibility_diagnoses", distinct=True),
                job_applications_count=Count("job_applications", distinct=True),
                accepted_job_applications_count=Count(
                    "job_applications",
                    filter=Q(job_applications__state=JobApplicationState.ACCEPTED),
                    distinct=True,
                ),
            )
            .all()
        )
        job_seekers_table = job_seekers.get_table()

        populate_table(job_seekers_table, batch_size=1000, querysets=[queryset])

    def populate_criteria(self):
        queryset = AdministrativeCriteria.objects.all()
        populate_table(criteria.TABLE, batch_size=1000, querysets=[queryset])

    def populate_job_applications(self):
        queryset = (
            JobApplication.objects.select_related(
                "to_company", "sender", "sender_company", "sender_prescriber_organization"
            )
            .prefetch_related("logs")
            .only(
                "pk",
                "created_at",
                "hiring_start_at",
                "origin",
                "sender_kind",
                "sender_company_id",
                "sender_company__kind",
                "sender_prescriber_organization__kind",
                "sender_prescriber_organization__name",
                "sender_prescriber_organization__code_safir_pole_emploi",
                "sender_prescriber_organization__is_authorized",
                "sender__last_name",
                "sender__first_name",
                "state",
                "refusal_reason",
                "job_seeker_id",
                "to_company_id",
                "to_company__kind",
                "to_company__brand",
                "to_company__name",
                "to_company__department",
                "approval_id",
                "approval_delivery_mode",
                "contract_type",
            )
            .exclude(origin=Origin.PE_APPROVAL)
            .filter(to_company_id__in=get_active_companies_pks())
            .all()
        )

        populate_table(job_applications.TABLE, batch_size=1000, querysets=[queryset])

    def populate_selected_jobs(self):
        """
        Populate associations between job applications and job descriptions.
        """
        queryset = (
            JobApplication.objects.exclude(origin=Origin.PE_APPROVAL)
            .filter(to_company_id__in=get_active_companies_pks())
            .exclude(selected_jobs=None)
            .values("pk", "selected_jobs__id")
        )

        populate_table(selected_jobs.TABLE, batch_size=10_000, querysets=[queryset])

    def populate_approvals(self):
        """
        Populate approvals table by merging Approvals and PoleEmploiApprovals.
        Some stats are available on both kinds of objects and some only
        on Approvals.
        We can link PoleEmploiApproval back to its PrescriberOrganization via
        the SAFIR code.
        """
        queryset1 = Approval.objects.prefetch_related(
            "user", "user__job_applications", "user__job_applications__to_company"
        ).all()
        queryset2 = PoleEmploiApproval.objects.filter(
            start_at__gte=approvals.POLE_EMPLOI_APPROVAL_MINIMUM_START_DATE
        ).all()

        populate_table(approvals.TABLE, batch_size=1000, querysets=[queryset1, queryset2])

    def populate_prolongations(self):
        queryset = Prolongation.objects.all()
        populate_table(prolongations.TABLE, batch_size=1000, querysets=[queryset])

    def populate_prolongation_requests(self):
        queryset = ProlongationRequest.objects.select_related(
            "prolongation",
            "deny_information",
        ).all()
        populate_table(prolongation_requests.TABLE, batch_size=1000, querysets=[queryset])

    def populate_institutions(self):
        queryset = Institution.objects.all()
        populate_table(institutions.TABLE, batch_size=1000, querysets=[queryset])

    def populate_evaluation_campaigns(self):
        queryset = EvaluationCampaign.objects.all()
        populate_table(evaluation_campaigns.TABLE, batch_size=1000, querysets=[queryset])

    def populate_evaluated_siaes(self):
        queryset = EvaluatedSiae.objects.prefetch_related(
            "evaluated_job_applications__evaluated_administrative_criteria"
        ).all()
        populate_table(evaluated_siaes.TABLE, batch_size=1000, querysets=[queryset])

    def populate_evaluated_job_applications(self):
        queryset = EvaluatedJobApplication.objects.prefetch_related("evaluated_administrative_criteria").all()
        populate_table(evaluated_job_applications.TABLE, batch_size=1000, querysets=[queryset])

    def populate_evaluated_criteria(self):
        queryset = EvaluatedAdministrativeCriteria.objects.all()
        populate_table(evaluated_criteria.TABLE, batch_size=1000, querysets=[queryset])

    def populate_users(self):
        queryset = User.objects.filter(
            kind__in=[UserKind.EMPLOYER, UserKind.PRESCRIBER, UserKind.LABOR_INSPECTOR], is_active=True
        )
        populate_table(users.TABLE, batch_size=1000, querysets=[queryset])

    def populate_memberships(self):
        siae_queryset = CompanyMembership.objects.active()
        prescriber_queryset = PrescriberMembership.objects.active()
        institution_queryset = InstitutionMembership.objects.active()

        populate_table(
            memberships.TABLE, batch_size=1000, querysets=[siae_queryset, prescriber_queryset, institution_queryset]
        )

    def populate_rome_codes(self):
        queryset = Rome.objects.all()

        populate_table(rome_codes.TABLE, batch_size=1000, querysets=[queryset])

    def populate_insee_codes(self):
        queryset = City.objects.all()

        populate_table(insee_codes.TABLE, batch_size=1000, querysets=[queryset])

    def populate_insee_codes_vs_post_codes(self):
        table_name = "codes_insee_vs_codes_postaux"
        self.stdout.write(f"Preparing content for {table_name} table...")

        rows = []
        for city in City.objects.all():
            for post_code in city.post_codes:
                row = {
                    "code_insee": city.code_insee,
                    "code_postal": post_code,
                }
                rows.append(row)

        df = get_df_from_rows(rows)
        store_df(df=df, table_name=table_name)

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

    def populate_enums(self):
        # TODO(vperron,dejafait): This works as long as we don't have several table creations in the same call.
        # If we someday want to create several tables, we will probably need to disable autocommit in our helper
        # functions and make it manually at the end.
        enum_to_table = {
            Origin: "c1_ref_origine_candidature",
            ContractType: "c1_ref_type_contrat",
            PrescriberOrganizationKind: "c1_ref_type_prescripteur",
            RefusalReason: "c1_ref_motif_de_refus",
        }
        for enum, table_name in enum_to_table.items():
            self.stdout.write(f"Preparing content for {table_name} table...")
            rows = [OrderedDict(code=str(item), label=item.label) for item in enum]
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
        if Approval.objects.exclude(user__kind=UserKind.JOB_SEEKER).exists():
            self.stdout.write("FATAL ERROR: At least one user has an approval but is not a job seeker")
            fatal_errors += 1

        if fatal_errors >= 1:
            raise RuntimeError(
                "The command completed all its actions successfully but at least one fatal error needs "
                "manual resolution, see command output"
            )

    @timeit
    def build_dbt_daily(self):
        build_dbt_daily()

    @timeit
    @monitor(monitor_slug="populate-metabase-emplois")
    @tenacity.retry(
        retry=tenacity.retry_if_not_exception_type(RuntimeError),
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_fixed(5),
        after=log_retry_attempt,
    )
    def handle(self, mode, **options):
        self.MODE_TO_OPERATION[mode]()
