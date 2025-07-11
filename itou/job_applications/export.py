import functools

from django.utils import timezone

from itou.approvals.models import Approval
from itou.job_applications.enums import JobApplicationState, SenderKind
from itou.siae_evaluations import enums as evaluation_enums
from itou.users.enums import Title, UserKind
from itou.utils.export import Format, to_streaming_response
from itou.utils.perms import utils as perms_utils
from itou.utils.templatetags import str_filters


JOB_APPLICATION_XSLX_FORMAT = {
    "Civilité candidat": Format.TEXT,
    "Nom candidat": Format.TEXT,
    "Prénom candidat": Format.TEXT,
    "Email candidat": Format.TEXT,
    "Téléphone candidat": Format.TEXT,
    "Date de naissance candidat": Format.DATE,
    "Ville candidat": Format.TEXT,
    "Département candidat": Format.TEXT,
    "Nom structure employeur": Format.TEXT,
    "Type employeur": Format.TEXT,
    "Métiers": Format.TEXT,
    "Source de la candidature": Format.TEXT,
    "Nom organisation prescripteur": Format.TEXT,
    "Nom utilisateur prescripteur": Format.TEXT,
    "Date de la candidature": Format.DATE,
    "Statut de la candidature": Format.TEXT,
    "Dates de début d’embauche": Format.DATE,
    "Dates de fin d’embauche": Format.DATE,
    "Motifs de refus": Format.TEXT,
    "Éligibilité IAE validée": Format.TEXT,
    "Eligible au contrôle": Format.TEXT,
    "Numéro PASS IAE": Format.TEXT,
    "Début PASS IAE": Format.DATE,
    "Fin PASS IAE": Format.DATE,
    "Statut PASS IAE": Format.TEXT,
}


def _get_prescriber_orgname(job_application):
    orgname = ""
    if job_application.sender_prescriber_organization:
        orgname = job_application.sender_prescriber_organization.display_name
    return orgname


def _get_prescriber_username(job_application):
    username = ""
    if job_application.sender is not None:
        username = job_application.sender.get_full_name()
    return username


def _get_selected_jobs(job_application):
    selected_jobs = "Candidature spontanée"
    if job_application.selected_jobs.all():
        selected_jobs = " ".join(map(lambda j: j.display_name, job_application.selected_jobs.all()))
    return selected_jobs


def _get_eligibility_status(job_application):
    eligibility = "non"
    # Eligibility diagnoses made by SIAE are ignored.
    if job_application.job_seeker.has_valid_diagnosis():
        eligibility = "oui"

    return eligibility


def _eligible_to_siae_evaluations(job_application):
    # See EvaluationCampaign.eligible_job_applications
    eligible = (
        job_application.approval_id is not None
        and job_application.to_company.kind in evaluation_enums.EvaluationSiaesKind.Evaluable
        and job_application.state == JobApplicationState.ACCEPTED
        and job_application.eligibility_diagnosis
        and job_application.eligibility_diagnosis.author_kind == UserKind.EMPLOYER
        and job_application.eligibility_diagnosis.author_siae_id == job_application.to_company_id
        and job_application.approval.start_at == job_application.hiring_start_at
        and job_application.approval.number.startswith(Approval.ASP_ITOU_PREFIX)
    )
    return "oui" if eligible else "non"


def _get_readable_sender_kind(job_application):
    """
    Converts itou internal prescriber kinds into something readable
    """
    kind = "Candidature spontanée"
    if job_application.sender_kind == SenderKind.EMPLOYER:
        kind = "Employeur"
        if job_application.sender_company == job_application.to_company:
            kind = "Ma structure"
    elif job_application.sender_kind == SenderKind.PRESCRIBER:
        kind = "Orienteur"
        if job_application.is_sent_by_authorized_prescriber:
            kind = "Prescripteur habilité"
    return kind


def _resolve_title(title, nir):
    if title:
        return title
    if nir:
        return {
            "1": Title.M,
            "2": Title.MME,
        }[nir[0]]
    return ""


def _serialize_job_application(job_application, request):
    job_seeker = job_application.job_seeker
    can_view_personal_information = perms_utils.can_view_personal_information(request, job_seeker)
    company = job_application.to_company

    numero_pass_iae = ""
    approval_start_date = None
    approval_end_date = None
    approval_state = None
    if approval := job_seeker.latest_common_approval:
        numero_pass_iae = approval.number
        approval_start_date = approval.start_at
        approval_end_date = approval.end_at
        approval_state = approval.get_state_display()

    return [
        _resolve_title(job_seeker.title, job_seeker.jobseeker_profile.nir) if can_view_personal_information else "",
        str_filters.mask_unless(job_seeker.last_name, predicate=can_view_personal_information),
        str_filters.mask_unless(job_seeker.first_name, predicate=can_view_personal_information),
        job_seeker.email if can_view_personal_information else "",
        job_seeker.phone if can_view_personal_information else "",
        job_seeker.jobseeker_profile.birthdate if can_view_personal_information else None,
        job_seeker.city if can_view_personal_information else "",
        job_seeker.post_code if can_view_personal_information else "",
        company.display_name,
        company.kind,
        _get_selected_jobs(job_application),
        _get_readable_sender_kind(job_application),
        _get_prescriber_orgname(job_application),
        _get_prescriber_username(job_application),
        timezone.make_naive(job_application.created_at).date(),
        job_application.get_state_display(),
        job_application.hiring_start_at,
        job_application.hiring_end_at,
        job_application.get_refusal_reason_display(),
        _get_eligibility_status(job_application),
        _eligible_to_siae_evaluations(job_application),
        numero_pass_iae,
        approval_start_date,
        approval_end_date,
        approval_state,
    ]


def _job_applications_serializer(queryset, *, request):
    return [_serialize_job_application(job_application, request) for job_application in queryset]


def stream_xlsx_export(job_applications, filename, request):
    """
    Takes a list of job application, converts them to XLSX and writes them in the provided stream
    The stream can be for instance an http response, a string (io.StringIO()) or a file
    """
    return to_streaming_response(
        job_applications,
        filename,
        list(JOB_APPLICATION_XSLX_FORMAT.keys()),
        functools.partial(_job_applications_serializer, request=request),
        columns=JOB_APPLICATION_XSLX_FORMAT.values(),
    )
