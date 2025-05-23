from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404
from django.template import loader
from django.utils.html import format_html

from itou.job_applications.models import JobApplication
from itou.users.enums import LackOfNIRReason
from itou.utils.perms.company import get_current_company_or_404


def tunnel_step_is_allowed(job_application):
    """
    Check if some steps of the tunnel are reachable or not
    given the current employee record status
    """

    employee_record = job_application.employee_record.order_by("-created_at").first()
    if not employee_record:
        return True

    return employee_record.ready.is_available()


def siae_is_allowed(job_application, siae):
    """
    SIAEs are only allowed to see "their" employee records
    """
    return job_application.to_company == siae


def can_create_employee_record(request, job_application_id) -> JobApplication:
    """
    Check if conditions / permissions are set to use the employee record views
    If a valid job_application_id is given, return a full-fledged
    JobApplication object reusable in view (skip one extra DB query)
    """
    # company only
    company = get_current_company_or_404(request)

    # company is eligible to employee record ?
    if not company.can_use_employee_record:
        raise PermissionDenied("Cette structure ne peut pas utiliser la gestion des fiches salarié'.")

    # We want to reuse a job application in view, but first check that all is ok
    job_application = get_object_or_404(
        JobApplication.objects.select_related(
            "approval",
            "to_company",
            "job_seeker",
            "job_seeker__jobseeker_profile",
        ),
        pk=job_application_id,
        to_company=company,
    )

    if job_application.job_seeker.jobseeker_profile.lack_of_nir_reason == LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER:
        raise PermissionDenied(
            format_html(
                """<p>Cette fiche salarié ne peut pas être modifiée.
                Veuillez d'abord régulariser le numéro de sécurité sociale.</p>
                {}""",
                loader.render_to_string(
                    "employee_record/includes/_regularize_nir_button.html",
                    context={"job_application": job_application},
                ),
            )
        )

    if not tunnel_step_is_allowed(job_application):
        raise PermissionDenied("Cette fiche salarié ne peut pas être modifiée.")

    # Finally, the reusable Holy Grail
    return job_application
