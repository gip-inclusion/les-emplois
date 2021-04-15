import csv

from itou.eligibility.models import EligibilityDiagnosis


JOB_APPLICATION_CSV_HEADERS = [
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
    "Nom prescripteur",
    "Date de la candidature",
    "Statut de la candidature",
    "Dates de début d’embauche",
    "Dates de fin d’embauche",
    "Motifs de refus",
    "Éligibilité IAE validée",
    "Numéro Pass IAE",
    "Début Pass IAE",
    "Fin Pass IAE",
]

DATE_FMT = "%d/%m/%Y"


def _format_date(dt):
    return dt.strftime(DATE_FMT) if dt else ""


def _get_prescriber_name(job_application):
    prescriber_name = ""
    if job_application.sender is not None:
        prescriber_name = job_application.sender.get_full_name()
    if job_application.sender_prescriber_organization:
        prescriber_name = prescriber_name
    return prescriber_name


def _get_selected_jobs(job_application):
    selected_jobs = "Candidature spontanée"
    if job_application.selected_jobs.exists:
        selected_jobs = " ".join(map(lambda j: j.display_name, job_application.selected_jobs.all()))
    return selected_jobs


def _get_eligibility_status(job_application):
    eligibility = "non"
    if EligibilityDiagnosis.objects.has_considered_valid(job_seeker=job_application.job_seeker):
        eligibility = "oui"

    return eligibility


def _job_application_as_dict(job_application):
    """
    The main CSV export mthod: it converts a JobApplication into a CSV array data
    """
    seeker = job_application.job_seeker
    siae = job_application.to_siae

    numero_pass_iae = ""
    approval_start_date = None
    approval_end_date = None
    if job_application.approval is not None:
        numero_pass_iae = job_application.approval.number
        approval_start_date = job_application.approval.start_at
        approval_end_date = job_application.approval.end_at

    return {
        "Nom candidat": seeker.last_name,
        "Prénom candidat": seeker.first_name,
        "Email candidat": seeker.email,
        "Téléphone candidat": seeker.phone,
        "Date de naissance candidat": _format_date(seeker.birthdate),
        "Ville candidat": seeker.city,
        "Département candidat": seeker.post_code,
        "Nom structure employeur": siae.display_name,
        "Type employeur": siae.kind,
        "Métiers": _get_selected_jobs(job_application),
        "Source de la candidature": job_application.display_sender_kind,
        "Nom prescripteur": _get_prescriber_name(job_application),
        "Date de la candidature": _format_date(job_application.created_at),
        "Statut de la candidature": job_application.get_state_display(),
        "Dates de début d’embauche": _format_date(job_application.hiring_start_at),
        "Dates de fin d’embauche": _format_date(job_application.hiring_end_at),
        "Motifs de refus": job_application.get_refusal_reason_display(),
        "Éligibilité IAE validée": _get_eligibility_status(job_application),
        "Numéro Pass IAE": numero_pass_iae,
        "Début Pass IAE": _format_date(approval_start_date),
        "Fin Pass IAE": _format_date(approval_end_date),
    }


def generate_csv_export(job_applications, stream):
    """
    Takes a list of job application, converts them to CSV and writes them in the provided stream
    The stream can be for instance an http response, a string (io.StringIO()) or a file
    """

    rows = [_job_application_as_dict(job_application) for job_application in job_applications.iterator()]

    writer = csv.DictWriter(stream, quoting=csv.QUOTE_ALL, fieldnames=JOB_APPLICATION_CSV_HEADERS)

    writer.writeheader()
    writer.writerows(rows)
