import csv


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


def _job_application_as_dict(job_application):
    """
    The main CSV export mthod: it converts a JobApplication into a CSV array data
    """
    job_seeker = job_application.job_seeker
    siae = job_application.to_siae

    numero_pass_iae = ""
    approval_start_date = None
    approval_end_date = None
    if job_seeker.approvals_wrapper.has_valid and job_seeker.approvals_wrapper.latest_approval is not None:
        approval = job_seeker.approvals_wrapper.latest_approval
        numero_pass_iae = approval.number
        approval_start_date = approval.start_at
        approval_end_date = approval.end_at

    return {
        "Nom candidat": job_seeker.last_name,
        "Prénom candidat": job_seeker.first_name,
        "Email candidat": job_seeker.email,
        "Téléphone candidat": job_seeker.phone,
        "Date de naissance candidat": _format_date(job_seeker.birthdate),
        "Ville candidat": job_seeker.city,
        "Département candidat": job_seeker.post_code,
        "Nom structure employeur": siae.display_name,
        "Type employeur": siae.kind,
        "Métiers": _get_selected_jobs(job_application),
        "Source de la candidature": job_application.display_sender_kind,
        "Nom organisation prescripteur": _get_prescriber_orgname(job_application),
        "Nom utilisateur prescripteur": _get_prescriber_username(job_application),
        "Date de la candidature": _format_date(job_application.created_at),
        "Statut de la candidature": job_application.get_state_display(),
        "Dates de début d’embauche": _format_date(job_application.hiring_start_at),
        "Dates de fin d’embauche": _format_date(job_application.hiring_end_at),
        "Motifs de refus": job_application.get_refusal_reason_display(),
        "Éligibilité IAE validée": _get_eligibility_status(job_application),
        "Numéro PASS IAE": numero_pass_iae,
        "Début PASS IAE": _format_date(approval_start_date),
        "Fin PASS IAE": _format_date(approval_end_date),
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
