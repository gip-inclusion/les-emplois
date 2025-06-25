from django import template
from django.urls import reverse
from django.utils.html import format_html

from itou.companies.enums import CompanyKind
from itou.utils.templatetags.matomo import matomo_event


register = template.Library()


@register.simple_tag
def accept_button(job_application, geiq_eligibility_diagnosis, *, batch_mode=False, next_url=None):
    # You need to include "apply/includes/geiq/no_allowance_modal.html" in the modal block
    # of any template using this templatetag

    class_kwargs = (
        "btn btn-lg btn-link-white btn-block btn-ico justify-content-center"
        if batch_mode
        else "btn btn-lg btn-white btn-block btn-ico"
    )

    if not job_application.accept.is_available():
        return ""

    if job_application.eligibility_diagnosis_by_siae_required():
        if suspension_explanation := job_application.to_company.get_active_suspension_text_with_dates():
            return format_html(
                """
                <button class="{} disabled"
                        data-bs-toggle="tooltip"
                        data-bs-placement="top"
                        data-bs-title="Vous ne pouvez pas valider les critères d'éligibilité suite aux mesures prises dans le cadre du contrôle a posteriori. {}">
                    <i class="ri-check-line fw-medium" aria-hidden="true"></i>
                    <span>Accepter</span>
                </button>
                """,  # noqa: E501
                class_kwargs,
                suspension_explanation,
            )
        url = reverse(
            "apply:eligibility",
            kwargs={"job_application_id": job_application.pk},
            query={"next_url": next_url} if next_url else None,
        )
        return format_html(
            """
            <a href="{}" class="{}">
                <i class="ri-check-line fw-medium" aria-hidden="true"></i>
                <span>Accepter</span>
            </a>
            """,
            url,
            class_kwargs,
        )

    if (
        job_application.to_company.kind != CompanyKind.GEIQ
        or geiq_eligibility_diagnosis
        and geiq_eligibility_diagnosis.is_valid
    ):
        url = reverse(
            "apply:accept",
            kwargs={"job_application_id": job_application.pk},
            query={"next_url": next_url} if next_url else None,
        )
        return format_html(
            """
            <a href="{}" class="{}" {}>
                <i class="ri-check-line fw-medium" aria-hidden="true"></i>
                <span>Accepter</span>
            </a>
            """,
            url,
            class_kwargs,
            matomo_event("candidature", "clic", "accept_application"),
        )

    # GEIQ companies without valid geiq_eligibility_diagnosis, modal in apply/process_details_company.html
    return format_html(
        """
        <button class="{}"
                data-bs-toggle="modal"
                data-bs-target="#confirm_no_allowance_modal">
            <i class="ri-check-line fw-medium" aria-hidden="true"></i>
            <span>Accepter</span>
        </button>
        """,
        class_kwargs,
    )
