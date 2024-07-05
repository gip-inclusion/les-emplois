from itou.job_applications.enums import SenderKind
from itou.users.enums import Title
from itou.utils.export import to_streaming_response


JOB_APPLICATION_CSV_HEADERS = [
    "Civilité candidat",
    "Nom candidat",
    "Prénom candidat",
    "Email candidat",
    "Téléphone candidat",
    "Date de naissance candidat",
    "Ville candidat",
    "Département candidat",
    "Nom structure employeur",
    "Type employeur",
    "Métiers",
    "Source de la candidature",
    "Nom organisation prescripteur",
    "Nom utilisateur prescripteur",
    "Date de la candidature",
    "Statut de la candidature",
    "Dates de début d’embauche",
    "Dates de fin d’embauche",
    "Motifs de refus",
    "Éligibilité IAE validée",
    "Numéro PASS IAE",
    "Début PASS IAE",
    "Fin PASS IAE",
    "Statut PASS IAE",
]

DATE_FMT = "%d/%m/%Y"


def _format_date(dt):
    return dt.strftime(DATE_FMT) if dt else ""


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
    if job_application.selected_jobs.exists:
        selected_jobs = " ".join(map(lambda j: j.display_name, job_application.selected_jobs.all()))
    return selected_jobs


def _get_eligibility_status(job_application):
    eligibility = "non"
    # Eligibility diagnoses made by SIAE are ignored.
    if job_application.job_seeker.has_valid_diagnosis():
        eligibility = "oui"

    return eligibility


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


def _serialize_job_application(job_application):
    job_seeker = job_application.job_seeker
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
        _resolve_title(job_seeker.title, job_seeker.jobseeker_profile.nir),
        job_seeker.last_name,
        job_seeker.first_name,
        job_seeker.email,
        job_seeker.phone,
        _format_date(job_seeker.birthdate),
        job_seeker.city,
        job_seeker.post_code,
        company.display_name,
        company.kind,
        _get_selected_jobs(job_application),
        _get_readable_sender_kind(job_application),
        _get_prescriber_orgname(job_application),
        _get_prescriber_username(job_application),
        _format_date(job_application.created_at),
        job_application.get_state_display(),
        _format_date(job_application.hiring_start_at),
        _format_date(job_application.hiring_end_at),
        job_application.get_refusal_reason_display(),
        _get_eligibility_status(job_application),
        numero_pass_iae,
        _format_date(approval_start_date),
        _format_date(approval_end_date),
        approval_state,
    ]


def _job_applications_serializer(queryset):
    return [_serialize_job_application(job_application) for job_application in queryset]


def stream_xlsx_export(job_applications, filename):
    """
    Takes a list of job application, converts them to XLSX and writes them in the provided stream
    The stream can be for instance an http response, a string (io.StringIO()) or a file
    """
    return to_streaming_response(
        job_applications,
        filename,
        JOB_APPLICATION_CSV_HEADERS,
        _job_applications_serializer,
    )
