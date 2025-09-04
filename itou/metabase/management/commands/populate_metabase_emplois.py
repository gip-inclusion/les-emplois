"""
Populate metabase database with transformed data from itou database.

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

import logging
from collections import OrderedDict

import tenacity
from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db.models import Count, F, Max, Min, OuterRef, Prefetch, Q, Subquery
from django.utils import timezone

from itou.analytics.models import Datum, StatsDashboardVisit
from itou.approvals.models import Approval, Prolongation, ProlongationRequest, Suspension
from itou.cities.models import City
from itou.common_apps.address.departments import DEPARTMENT_TO_REGION, DEPARTMENTS
from itou.companies.enums import ContractType
from itou.companies.models import Company, CompanyMembership, JobDescription
from itou.eligibility.enums import AdministrativeCriteriaLevel
from itou.eligibility.models import AdministrativeCriteria, EligibilityDiagnosis, SelectedAdministrativeCriteria
from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.institutions.models import Institution, InstitutionMembership
from itou.job_applications.enums import JobApplicationState, Origin, RefusalReason, SenderKind
from itou.job_applications.models import JobApplication, JobApplicationTransitionLog, JobApplicationWorkflow
from itou.jobs.models import Rome
from itou.metabase.dataframes import get_df_from_rows, store_df
from itou.metabase.db import populate_table
from itou.metabase.tables import (
    analytics,
    approvals,
    companies,
    criteria,
    evaluated_criteria,
    evaluated_job_applications,
    evaluated_siaes,
    evaluation_campaigns,
    gps,
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
    suspensions,
    users,
)
from itou.metabase.utils import build_dbt_daily
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
from itou.utils.slack import send_slack_message


logger = logging.getLogger(__name__)


def log_retry_attempt(retry_state):
    logging.info("Attempt failed with outcome=%s", retry_state.outcome)


class Command(BaseCommand):
    help = "Populate metabase database."

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Order in the dict is the order in which the function are going to be called, hence referential data on top
        self.MODE_TO_OPERATION = {
            # Referential data
            "references": self.populate_references,
            "enums": self.populate_enums,
            # Business data
            "analytics": self.populate_analytics,
            "companies": self.populate_companies,
            "job_descriptions": self.populate_job_descriptions,
            "organizations": self.populate_organizations,
            "job_seekers": self.populate_job_seekers,
            "criteria": self.populate_criteria,
            "job_applications": self.populate_job_applications,
            "selected_jobs": self.populate_selected_jobs,
            "approvals": self.populate_approvals,
            "prolongations": self.populate_prolongations,
            "prolongation_requests": self.populate_prolongation_requests,
            "suspensions": self.populate_suspensions,
            "institutions": self.populate_institutions,
            "evaluation_campaigns": self.populate_evaluation_campaigns,
            "evaluated_siaes": self.populate_evaluated_siaes,
            "evaluated_job_applications": self.populate_evaluated_job_applications,
            "evaluated_criteria": self.populate_evaluated_criteria,
            "users": self.populate_users,
            "memberships": self.populate_memberships,
            "gps_groups": self.populate_gps_groups,
            "gps_memberships": self.populate_gps_memberships,
        }

    def add_arguments(self, parser):
        parser.add_argument("--mode", required=True, choices=["all", *sorted(self.MODE_TO_OPERATION)])

    def populate_analytics(self):
        populate_table(analytics.AnalyticsTable, batch_size=100_000, querysets=[Datum.objects.all()])
        populate_table(
            analytics.DashboardVisitTable, batch_size=100_000, querysets=[StatsDashboardVisit.objects.all()]
        )

    def populate_companies(self):
        ONE_MONTH_AGO = timezone.now() - timezone.timedelta(days=30)
        queryset = (
            Company.objects.active()
            .select_related("convention", "insee_city")
            .prefetch_related(
                Prefetch(
                    "convention__siaes",
                    queryset=Company.objects.select_related("insee_city").only(
                        "source",  # Company.canonical_company
                        "convention",  # Company.canonical_company
                        "siret",  # is_aci_convergence
                        "address_line_1",  # get_address_columns
                        "address_line_2",  # get_address_columns
                        "post_code",  # get_post_code_column
                        "insee_city__code_insee",  # get_code_commune
                        "city",  # get_address_columns
                        "coords",  # get_address_columns
                        "department",  # get_department_and_region_columns
                    ),
                ),
            )
            .annotate(
                active_memberships_count=(
                    CompanyMembership.objects.active()
                    .filter(company=OuterRef("pk"))
                    .values("company")
                    .annotate(count=Count("*"))
                    .values("count")[:1]
                ),
                first_membership_join_date=(
                    CompanyMembership.objects.filter(company=OuterRef("pk"))
                    .values("company")
                    .annotate(min=Min("joined_at"))
                    .values("min")[:1]
                ),
                last_login_date=(
                    CompanyMembership.objects.filter(company=OuterRef("pk"))
                    .values("company")
                    .annotate(max=Max("user__last_login"))
                    .values("max")[:1]
                ),
                job_descriptions_active_count=(
                    JobDescription.objects.filter(company=OuterRef("pk"), is_active=True)
                    .values("company")
                    .annotate(count=Count("*"))
                    .values("count")[:1]
                ),
                job_descriptions_inactive_count=(
                    JobDescription.objects.filter(company=OuterRef("pk"), is_active=False)
                    .values("company")
                    .annotate(count=Count("*"))
                    .values("count")[:1]
                ),
                last_job_application_transition_date=Max(
                    "job_applications_received__logs__timestamp",
                    filter=~Q(job_applications_received__logs__to_state=JobApplicationState.OBSOLETE),
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
            )
            .only(
                "convention",
                "convention__asp_id",
                "kind",
                "brand",  # Company.display_name
                "name",  # Company.display_name
                "description",
                "siret",
                "source",
                "naf",
                "email",
                "auth_email",
                "address_line_1",  # get_address_columns
                "address_line_2",  # get_address_columns
                "post_code",  # get_post_code_column
                "insee_city__code_insee",  # get_code_commune
                "city",  # get_address_columns
                "coords",  # get_address_columns
                "department",  # get_department_and_region_columns
            )
        )

        populate_table(companies.TABLE, batch_size=10_000, querysets=[queryset])

    def populate_job_descriptions(self):
        queryset = (
            JobDescription.objects.select_related(
                "company",
                "appellation__rome",
            )
            .filter(company_id__in=Company.objects.active())
            .with_job_applications_count()
            .all()
        )
        populate_table(job_descriptions.TABLE, batch_size=50_000, querysets=[queryset])

    def populate_organizations(self):
        """
        Populate prescriber organizations,
        and add a special "ORG_OF_PRESCRIBERS_WITHOUT_ORG" to gather stats
        of prescriber users *without* any organization.
        """
        active_user_created_job_applications_filter = Q(
            ~Q(jobapplication__origin=Origin.PE_APPROVAL)
            & Q(jobapplication__to_company_id__in=Company.objects.active())
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
            PrescriberOrganization.objects.select_related("insee_city")
            .annotate(
                job_applications_count=job_applications_count,
                accepted_job_applications_count=accepted_job_applications_count,
                last_job_application_creation_date=last_job_application_creation_date,
                active_memberships_count=(
                    PrescriberMembership.objects.active()
                    .filter(organization=OuterRef("pk"))
                    .values("organization")
                    .annotate(count=Count("*"))
                    .values("count")[:1]
                ),
                first_membership_join_date=(
                    PrescriberMembership.objects.filter(organization=OuterRef("pk"))
                    .values("organization")
                    .annotate(min=Min("joined_at"))
                    .values("min")[:1]
                ),
                last_login_date=(
                    PrescriberMembership.objects.filter(organization=OuterRef("pk"))
                    .values("organization")
                    .annotate(max=Max("user__last_login"))
                    .values("max")[:1]
                ),
            )
            .only(
                "siret",
                "name",
                "kind",
                "authorization_status",
                "address_line_1",  # get_address_columns
                "address_line_2",  # get_address_columns
                "post_code",  # get_post_code_column
                "insee_city__code_insee",  # get_code_commune
                "city",  # get_address_columns
                "coords",  # get_address_columns
                "department",  # get_department_and_region_columns
                "code_safir_pole_emploi",
                "members__last_login",  # get_establishment_last_login_date_column
                "is_brsa",
            )
        )

        populate_table(
            organizations.TABLE,
            batch_size=10_000,
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
            .select_related("jobseeker_profile", "created_by")
            .prefetch_related(
                Prefetch(
                    "eligibility_diagnoses",
                    queryset=(
                        EligibilityDiagnosis.objects.select_related(
                            "author_prescriber_organization",
                            "author_siae",
                        )
                        .prefetch_related(
                            Prefetch(
                                "selected_administrative_criteria",
                                SelectedAdministrativeCriteria.objects.only(
                                    "administrative_criteria_id",
                                    "eligibility_diagnosis_id",
                                    "certified",
                                    "certified_at",
                                    "certification_period",
                                ),
                            ),
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
                        .only(
                            "created_at",
                            "expires_at",
                            "author_kind",
                            "author_prescriber_organization_id",
                            "author_siae_id",
                            "author_siae__kind",  # get_latest_diagnosis_author_sub_kind
                            "author_prescriber_organization__kind",  # get_latest_diagnosis_author_sub_kind
                            "author_siae__brand",  # get_latest_diagnosis_author_display_name
                            "author_siae__name",  # get_latest_diagnosis_author_display_name
                            "author_prescriber_organization__name",  # get_latest_diagnosis_author_display_name
                            "job_seeker_id",  # Origin unknown, seems needed by the ORM somehow
                        )
                        .order_by("-created_at")[:1]
                    ),
                    to_attr="last_eligibility_diagnosis",
                ),
            )
            .annotate(
                eligibility_diagnoses_count=Count("eligibility_diagnoses", distinct=True),
                job_applications_count=Count("job_applications", distinct=True),
                accepted_job_applications_count=Count(
                    "job_applications",
                    filter=Q(job_applications__state=JobApplicationState.ACCEPTED),
                    distinct=True,
                ),
                last_hiring_company_kind=Subquery(
                    JobApplication.objects.accepted()
                    .filter(job_seeker=OuterRef("pk"))
                    .values("to_company__kind")
                    .order_by("-created_at")[:1]
                ),
            )
            .only(
                "jobseeker_profile__nir",
                "jobseeker_profile__birthdate",  # get_user_age_in_years
                "date_joined",
                "created_by__kind",  # get_user_signup_kind
                "created_by__is_staff",  # get_user_signup_kind
                "identity_provider",
                "jobseeker_profile__pole_emploi_id",
                "last_login",
                "first_login",
                "post_code",  # get_post_code_column
                "department",  # get_department_and_region_columns
                "coords",  # get_job_seeker_qpv_info
                "geocoding_score",  # get_job_seeker_qpv_info
            )
            .all()
        )
        job_seekers_table = job_seekers.get_table()

        populate_table(job_seekers_table, batch_size=20_000, querysets=[queryset])

    def populate_criteria(self):
        queryset = AdministrativeCriteria.objects.all()
        populate_table(criteria.TABLE, batch_size=10_000, querysets=[queryset])

    def populate_job_applications(self):
        queryset = (
            JobApplication.objects.select_related(
                "to_company", "sender", "sender_company", "sender_prescriber_organization"
            )
            .exclude(origin=Origin.PE_APPROVAL)
            .filter(to_company_id__in=Company.objects.active())
            .annotate(
                transition_accepted_date=JobApplicationTransitionLog.objects.filter(
                    job_application=OuterRef("pk"),
                    transition=JobApplicationWorkflow.TRANSITION_ACCEPT,
                )
                .values("job_application")
                .annotate(first_timestamp=Min("timestamp"))
                .values("first_timestamp"),
                time_spent_from_new_to_processing=Subquery(
                    JobApplicationTransitionLog.objects.filter(
                        job_application=OuterRef("pk"),
                        transition=JobApplicationWorkflow.TRANSITION_PROCESS,
                    )
                    .values("job_application")
                    .annotate(first_timestamp=Min("timestamp"))
                    .values("first_timestamp")
                )
                - F("created_at"),
                time_spent_from_new_to_accepted_or_refused=Subquery(
                    JobApplicationTransitionLog.objects.filter(
                        job_application=OuterRef("pk"),
                        to_state__in=[JobApplicationState.ACCEPTED, JobApplicationState.REFUSED],
                    )
                    .values("job_application")
                    .annotate(first_timestamp=Min("timestamp"))
                    .values("first_timestamp")
                )
                - F("created_at"),
            )
            .only(
                "archived_at",
                "refusal_reason",
                "created_at",
                "hiring_start_at",
                "processed_at",
                "state",
                "sender_kind",  # get_job_application_origin
                "sender_prescriber_organization__authorization_status",  # get_job_application_origin
                "sender_company__kind",  # get_job_application_detailed_origin
                "sender_prescriber_organization__kind",  # get_job_application_detailed_origin
                "sender_company_id",
                "origin",
                "refusal_reason",
                "job_seeker_id",
                "to_company_id",
                "to_company__kind",
                "to_company__brand",  # Company.display_name
                "to_company__name",  # Company.display_name
                "to_company__department",  # get_department_and_region_columns
                "sender_prescriber_organization__name",  # get_ja_sender_organization_name
                "sender_prescriber_organization__code_safir_pole_emploi",  # get_ja_sender_organization_safir
                "sender__last_name",  # get_ja_sender_full_name_if_pe_or_spip
                "sender__first_name",  # get_ja_sender_full_name_if_pe_or_spip
                "approval_delivery_mode",
                "contract_type",
                "resume_id",
            )
        )

        populate_table(job_applications.TABLE, batch_size=20_000, querysets=[queryset])

    def populate_selected_jobs(self):
        """
        Populate associations between job applications and job descriptions.
        """
        queryset = JobApplication.selected_jobs.through.objects.exclude(
            jobapplication__origin=Origin.PE_APPROVAL
        ).filter(jobapplication__to_company_id__in=Company.objects.active())

        populate_table(selected_jobs.TABLE, batch_size=100_000, querysets=[queryset])

    def populate_approvals(self):
        only_fields = {
            "number",  # get_approval_type
            "start_at",
            "end_at",
        }
        queryset = (
            Approval.objects.select_related("user")
            .annotate(
                last_hiring_company_pk=(
                    JobApplication.objects.accepted()
                    .filter(job_seeker=OuterRef("user"))
                    .values("to_company")
                    .order_by("-created_at")[:1]
                )
            )
            .only(
                *only_fields,
                "user_id",
                "origin",
            )
        )
        populate_table(approvals.TABLE, batch_size=50_000, querysets=[queryset])

    def populate_prolongations(self):
        queryset = Prolongation.objects.all()
        populate_table(prolongations.TABLE, batch_size=100_000, querysets=[queryset])

    def populate_prolongation_requests(self):
        queryset = ProlongationRequest.objects.select_related(
            "prolongation",
            "deny_information",
        ).all()
        populate_table(prolongation_requests.TABLE, batch_size=50_000, querysets=[queryset])

    def populate_suspensions(self):
        queryset = Suspension.objects.all()
        populate_table(suspensions.TABLE, batch_size=100_000, querysets=[queryset])

    def populate_institutions(self):
        queryset = Institution.objects.all()
        populate_table(institutions.TABLE, batch_size=10_000, querysets=[queryset])

    def populate_evaluation_campaigns(self):
        queryset = EvaluationCampaign.objects.all()
        populate_table(evaluation_campaigns.TABLE, batch_size=10_000, querysets=[queryset])

    def populate_evaluated_siaes(self):
        queryset = EvaluatedSiae.objects.prefetch_related(
            "evaluated_job_applications__evaluated_administrative_criteria"
        ).all()
        populate_table(evaluated_siaes.TABLE, batch_size=5_000, querysets=[queryset])

    def populate_evaluated_job_applications(self):
        queryset = EvaluatedJobApplication.objects.prefetch_related("evaluated_administrative_criteria").all()
        populate_table(evaluated_job_applications.TABLE, batch_size=20_000, querysets=[queryset])

    def populate_evaluated_criteria(self):
        queryset = EvaluatedAdministrativeCriteria.objects.all()
        populate_table(evaluated_criteria.TABLE, batch_size=100_000, querysets=[queryset])

    def populate_users(self):
        queryset = User.objects.filter(kind__in=UserKind.professionals(), is_active=True)
        populate_table(users.TABLE, batch_size=50_000, querysets=[queryset])

    def populate_memberships(self):
        siae_queryset = CompanyMembership.objects.active()
        prescriber_queryset = PrescriberMembership.objects.active()
        institution_queryset = InstitutionMembership.objects.active()

        populate_table(
            memberships.TABLE, batch_size=100_000, querysets=[siae_queryset, prescriber_queryset, institution_queryset]
        )

    def populate_references(self):
        # DB referential
        populate_table(rome_codes.TABLE, batch_size=100_000, querysets=[Rome.objects.all()])
        populate_table(insee_codes.TABLE, batch_size=50_000, querysets=[City.objects.all()])
        # Code referential
        rows = []
        for dpt_code, dpt_name in DEPARTMENTS.items():
            # We want to preserve the order of columns.
            row = OrderedDict()
            row["code_departement"] = dpt_code
            row["nom_departement"] = dpt_name
            row["nom_region"] = DEPARTMENT_TO_REGION[dpt_code]
            rows.append(row)
        store_df(df=get_df_from_rows(rows), table_name="departements")

    def populate_enums(self):
        # TODO(vperron,dejafait): This works as long as we don't have several table creations in the same call.
        # If we someday want to create several tables, we will probably need to disable autocommit in our helper
        # functions and make it manually at the end.
        enum_to_table = {
            Origin: "c1_ref_origine_candidature",
            ContractType: "c1_ref_type_contrat",
            PrescriberOrganizationKind: "c1_ref_type_prescripteur",
            RefusalReason: "c1_ref_motif_de_refus",
            Suspension.Reason: "c1_ref_motif_suspension",
        }
        for enum, table_name in enum_to_table.items():
            self.logger.info("Preparing content for %s table...", table_name)
            rows = [OrderedDict(code=str(item), label=item.label) for item in enum]
            df = get_df_from_rows(rows)
            store_df(df=df, table_name=table_name)

    def populate_gps_groups(self):
        queryset = FollowUpGroup.objects.all().annotate(beneficiary_department=F("beneficiary__department"))
        populate_table(gps.GroupsTable, batch_size=100_000, querysets=[queryset])

    def populate_gps_memberships(self):
        queryset = (
            FollowUpGroupMembership.objects.all()
            .annotate(
                companies_departments=ArrayAgg(
                    "member__companymembership__company__department",
                    filter=Q(member__companymembership__is_active=True),
                    distinct=True,
                    order_by="member__companymembership__company__department",
                )
            )
            .annotate(
                prescriber_departments=ArrayAgg(
                    "member__prescribermembership__organization__department",
                    filter=Q(member__prescribermembership__is_active=True),
                    distinct=True,
                    order_by="member__prescribermembership__organization__department",
                )
            )
        )
        populate_table(gps.MembershipsTable, batch_size=100_000, querysets=[queryset])

    @tenacity.retry(
        retry=tenacity.retry_if_not_exception_type(RuntimeError),
        stop=tenacity.stop_after_attempt(3),
        wait=tenacity.wait_fixed(5),
        after=log_retry_attempt,
    )
    def handle(self, *, mode, **options):
        if mode == "all":
            send_slack_message(
                ":rocket: lancement mise à jour de données C1 -> Metabase", url=settings.PILOTAGE_SLACK_WEBHOOK_URL
            )
            for operation in self.MODE_TO_OPERATION.values():
                operation()
            build_dbt_daily()
            send_slack_message(
                ":white_check_mark: succès mise à jour de données C1 -> Metabase",
                url=settings.PILOTAGE_SLACK_WEBHOOK_URL,
            )
        else:
            self.MODE_TO_OPERATION[mode]()
