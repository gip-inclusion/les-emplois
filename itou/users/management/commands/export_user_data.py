import csv
import pathlib
import tempfile
import zipfile

import sentry_sdk
from allauth.account.forms import EmailAddress
from django.apps import apps
from django.contrib.admin.models import LogEntry
from django.utils.text import slugify
from django_otp.plugins.otp_totp.models import TOTPDevice
from rest_framework.authtoken.models import Token, TokenProxy

from itou.approvals.models import Approval, Prolongation, ProlongationRequest, Suspension
from itou.communications.models import NotificationSettings
from itou.companies.models import Company, CompanyMembership, Contract, SiaeConvention
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.eligibility.models.iae import EligibilityDiagnosis
from itou.employee_record.models import EmployeeRecordTransitionLog
from itou.geiq_assessments.models import Assessment, AssessmentTransitionLog
from itou.insertion.models import MobilizationEvent, Orientation
from itou.institutions.models import Institution, InstitutionMembership
from itou.invitations.models import EmployerInvitation, LaborInspectorInvitation, PrescriberWithOrgInvitation
from itou.job_applications.models import JobApplication, JobApplicationComment, JobApplicationTransitionLog
from itou.nexus.models import ActivatedService
from itou.otp.models import ItouStaticDevice, ItouTOTPDevice
from itou.prescribers.models import PrescriberMembership, PrescriberOrganization
from itou.rdv_insertion.models import Appointment, InvitationRequest, Participation
from itou.search.models import SavedSearch
from itou.users.models import (
    IdentityCertification,
    JobSeekerAssignment,
    JobSeekerProfile,
    NirModificationRequest,
    User,
)
from itou.utils.command import BaseCommand


NO_EXPORTER = object()


sentry_sdk.init(dsn="")  # FIXME: DEBUG ONLY


class Command(BaseCommand):
    """Export (in zipped CSV files) user's data"""

    ATOMIC_HANDLE = False
    AUTO_TRIGGER_CONTEXT = False

    def add_arguments(self, parser):
        parser.add_argument("user_id")

    def handle(self, user_id, **options):
        user = User.objects.filter(pk=user_id).first()
        if not user:
            self.stderr.write("Cannot not find this user.")
            return

        # FIXME: for now, only job seekers are supported.
        if not user.is_job_seeker:
            self.stderr.write("User is not a job seeker.")
            return

        zip_path = self._export_data(user)

        self.stdout.write(f"Data has been exported to {zip_path}")

    def _export_data(self, user):
        path_prefix = f"user-data-export-{user.pk}-"
        base_dir = pathlib.Path(tempfile.mkdtemp(prefix=path_prefix))
        csv_paths = []

        # FIXME: remove `filter_key`?
        for model, exporter in EXPORTERS.items():
            if exporter is NO_EXPORTER:
                continue
            headers, rows = exporter(user)
            if not rows:
                continue
            csv_path = pathlib.Path(base_dir / f"{slugify(model._meta.verbose_name)}.csv")
            write_csv(csv_path, headers, rows)
            csv_paths.append(csv_path)

        _, zip_path = tempfile.mkstemp(prefix=path_prefix, suffix=".zip")
        with zipfile.ZipFile(
            zip_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=5,
        ) as zip_file:
            for csv_path in csv_paths:
                zip_file.write(csv_path, arcname=csv_path.name)
        return zip_path


def write_csv(csv_path, headers, rows):
    with csv_path.open("w", encoding="utf-8") as fp:
        writer = csv.writer(fp)
        writer.writerow(headers)
        writer.writerows(rows)


def _default_exporter(model, filter_key, fields, filter_value):
    # `filter_key` is usually "user" or "job_seeker", and
    # `filter_value" is usually the `User` instance.
    headers = [get_verbose_name(model, field) for field in fields]
    items = model.objects.filter(**{filter_key: filter_value})
    rows = items.values_list(*fields)
    return headers, rows


def export_approvals(user):
    fields = [
        "number",
        "start_at",
        "end_at",
        "created_at",
    ]
    return _default_exporter(Approval, "user", fields, user)


def export_contracts(user):
    fields = [
        "company__name",
        "start_date",
        "end_date",
        "updated_at",
    ]
    return _default_exporter(Contract, "job_seeker_id", fields, user.pk)


def export_eligibility_diagnoses(user):
    fields = (
        "author_prescriber_organization__name",
        "author_siae__name",
        "created_at",
        "updated_at",
        "expires_at",
        "administrative_criteria__name",
        "administrative_criteria__desc",
        "administrative_criteria__written_proof",
        "administrative_criteria__written_proof_url",
        "administrative_criteria__written_proof_validity",
        "administrative_criteria__kind",
    )
    return _default_exporter(EligibilityDiagnosis, "job_seeker_id", fields, user.pk)


def export_identity_certifications(user):
    fields = [
        "certifier",
        "certified_at",
    ]
    return _default_exporter(IdentityCertification, "jobseeker_profile__pk", fields, user.pk)


def export_job_applications(user):
    fields = [
        # FIXME: we should include the file itself in the ZIP
        "resume__key",
        "to_company__name",
        "sender_company__name",
        "sender_prescriber_organization__name",
        "state",
        "archived_at",
        "selected_jobs__custom_name",
        "selected_jobs__description",
        "selected_jobs__contract_type",
        "selected_jobs__other_contract_type",
        "selected_jobs__location",
        "selected_jobs__hours_per_week",
        "selected_jobs__profile_description",
        "selected_jobs__market_context_description",
        "hired_job__custom_name",
        "hired_job__description",
        "hired_job__contract_type",
        "hired_job__other_contract_type",
        "hired_job__location",
        "hired_job__hours_per_week",
        "hired_job__profile_description",
        "hired_job__market_context_description",
        "message",
        "answer",
        # FIXME: also include `refusal_reason`, but only if
        # `refusal_reason_shared_with_job_seeker` is true.
        "hiring_start_at",
        "hiring_end_at",
        "origin",
        "approval__number",
        "contract_type",
        "nb_hours_per_week",
        "contract_type_details",
        "qualification_type",
        "qualification_level",
    ]
    return _default_exporter(JobApplication, "job_seeker_id", fields, user.pk)


def export_job_seeker_profiles(user):
    fields = (
        "birthdate",
        "birth_place",
        "birth_country",
        "nir",
        "lack_of_nir_reason",
        "education_level",
        "resourceless",
        "rqth_employee",
        "oeth_employee",
        "pole_emploi_since",
        "unemployed_since",
        "has_rsa_allocation",
        "rsa_allocation_since",
        "ass_allocation_since",
        "aah_allocation_since",
        "are_allocation_since",
        "activity_bonus_since",
        "cape_freelance",
        "cesa_freelance",
        "mean_monthly_income_before_process",
        "eiti_contributions",
        "ase_exit",
        "isolated_parent",
        "housing_issue",
        "refugee",
        "detention_exit_or_ppsmj",
        "low_level_in_french",
    )
    return _default_exporter(JobSeekerProfile, "user", fields, user)


def export_appointment_participations(user):
    fields = (
        "appointment__company__name",
        "appointment__location__name",
        "appointment__location__address",
        "appointment__location__phone_number",
        "appointment__status",
        "appointment__reason_category",
        "appointment__reason",
        "appointment__start_at",
        "appointment__duration",
        "appointment__canceled_at",
        "appointment__address",
        "status",
    )
    return _default_exporter(Participation, "job_seeker_id", fields, user.pk)


def export_users(user):
    fields = (
        "public_id",
        "first_name",
        "last_name",
        "title",
        "email",
        "phone",
        "address_line_1",
        "address_line_2",
        "post_code",
        "city",
        "department",
        "date_joined",
        "first_login",
        "last_login",
        "has_completed_welcoming_tour",
        "terms_accepted_at",
    )
    return _default_exporter(User, "pk", fields, user.pk)


def get_verbose_name(model, field_name):
    if "__" not in field_name:  # not a relation
        return model._meta.get_field(field_name).verbose_name
    relation_name, rest = field_name.split("__", 1)
    field = model._meta.get_field(relation_name)
    relation_model = field.related_model
    prefix = field.verbose_name
    return " - ".join((prefix, get_verbose_name(relation_model, rest)))


def get_related_models(target_model):
    models = set()

    for model in apps.get_models():
        for field in model._meta.get_fields():
            if not field.is_relation:
                continue
            if field.auto_created:
                continue
            if field.related_model is target_model:
                models.add(model)

    return models


EXPORTERS = {
    # allauth.account
    EmailAddress: NO_EXPORTER,
    # approval
    Approval: export_approvals,
    Prolongation: NO_EXPORTER,  # FIXME: should be exported
    ProlongationRequest: NO_EXPORTER,  # not relevant
    Suspension: NO_EXPORTER,  # FIXME: should be exported
    # communication
    NotificationSettings: NO_EXPORTER,
    # companies
    Company: NO_EXPORTER,
    CompanyMembership: NO_EXPORTER,  # FIXME: should be exported
    Contract: export_contracts,
    SiaeConvention: NO_EXPORTER,
    # django.contrib.admin
    LogEntry: NO_EXPORTER,  # no personal data
    # django_otp.plugins.otp_totp
    TOTPDevice: NO_EXPORTER,  # no personal data
    # eligibility
    GEIQEligibilityDiagnosis: NO_EXPORTER,  # FIXME: should be exported
    EligibilityDiagnosis: export_eligibility_diagnoses,
    # employee_record
    EmployeeRecordTransitionLog: NO_EXPORTER,  # workflow log
    # geiq_assessment
    Assessment: NO_EXPORTER,  # no personal data
    AssessmentTransitionLog: NO_EXPORTER,  # workflow log
    # insertion
    MobilizationEvent: NO_EXPORTER,  # no personal data
    Orientation: NO_EXPORTER,  # FIXME: should be exported?
    Institution: NO_EXPORTER,  # no personal data
    InstitutionMembership: NO_EXPORTER,  # FIXME: should be exported
    # invitation
    EmployerInvitation: NO_EXPORTER,  # no personal data
    LaborInspectorInvitation: NO_EXPORTER,  # no personal data
    PrescriberWithOrgInvitation: NO_EXPORTER,  # no personal data
    # job_applications
    JobApplication: export_job_applications,
    JobApplicationComment: NO_EXPORTER,  # not relevant
    JobApplicationTransitionLog: NO_EXPORTER,  # workflow log
    # nexus
    ActivatedService: NO_EXPORTER,  # no personal data
    # otp
    ItouStaticDevice: NO_EXPORTER,  # no personal data
    ItouTOTPDevice: NO_EXPORTER,  # no personal data
    # prescribers
    PrescriberMembership: NO_EXPORTER,  # FIXME: should be exported
    PrescriberOrganization: NO_EXPORTER,  # no personal data
    # rdv_insertion
    Appointment: NO_EXPORTER,  # exported through `Participation`
    InvitationRequest: NO_EXPORTER,  # FIXME: to be exported
    Participation: export_appointment_participations,
    # search
    SavedSearch: NO_EXPORTER,  # not relevant
    # users
    IdentityCertification: export_identity_certifications,
    JobSeekerAssignment: NO_EXPORTER,  # not relevant
    JobSeekerProfile: export_job_seeker_profiles,
    NirModificationRequest: NO_EXPORTER,  # FIXME: should be exported
    User: export_users,
    # rest_framework.authtoken
    Token: NO_EXPORTER,  # secret
    TokenProxy: NO_EXPORTER,  # secret
}


def check_exporters():
    models = set()
    for model in (User, JobSeekerProfile):
        models |= get_related_models(model)
    missing = models - set(EXPORTERS)
    if missing:
        raise ValueError(f"Missing exporters for models: {missing}")


check_exporters()
