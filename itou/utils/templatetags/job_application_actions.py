from django import template
from django.urls import reverse
from django.utils.html import format_html

from itou.utils.templatetags.matomo import matomo_event


register = template.Library()


@register.simple_tag
def accept_button(job_application, *, next_url=None):
    class_kwargs = "btn btn-lg btn-link-white btn-block btn-ico justify-content-center"

    if not job_application.accept.is_available():
        return ""

    if job_application.eligibility_diagnosis_by_siae_required() and (
        suspension_explanation := job_application.to_company.get_active_suspension_text_with_dates()
    ):
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
    return format_html(
        """
        <a href="{}" class="{}" {}>
            <i class="ri-check-line fw-medium" aria-hidden="true"></i>
            <span>Accepter</span>
        </a>
        """,
        reverse(
            "apply:start-accept",
            kwargs={"job_application_id": job_application.pk},
            query={"next_url": next_url} if next_url else None,
        ),
        class_kwargs,
        matomo_event("candidature", "clic", "accept_application"),
    )
