"""The job seeker's file, folded at the bottom of their page: one part per subject, each leading to the existing tab.

Each part is built here as data, with the scope of the tab it leads to, so that the template lays them all out the
same way: a summary line with its badge, then a few facts, a label and its value per line. A part without facts has
nothing to open: its summary line says it all.
"""

import dataclasses

from django.urls import reverse
from django.utils import timezone

from itou.approvals.enums import ApprovalStatus
from itou.companies.models import ProSupportReport
from itou.users.perms import can_view_pro_support_report
from itou.www.next_steps_views.advisors import _job_application_url, _job_applications
from itou.www.next_steps_views.situation import contract_place


NBSP = " "
# The latest ones only: the tab lists them all.
JOB_APPLICATIONS_SHOWN = 3
CONTRACTS_SHOWN = 3

APPROVAL_BADGES = {
    ApprovalStatus.VALID: ("Valide", "success"),
    ApprovalStatus.FUTURE: ("À venir", "success"),
    ApprovalStatus.SUSPENDED: ("Suspendu", "info"),
    ApprovalStatus.EXPIRED: ("Expiré", "danger"),
}


def _badge(tone):
    """itou-theme's light badge colours; "muted" for what is over."""
    return "bg-light text-muted" if tone == "muted" else f"bg-{tone}-lighter text-{tone}"


def _fr(date):
    return f"{date:%d/%m/%Y}"


def _period(start, end):
    return f"Du {_fr(start)} au {_fr(end)}" if end else f"Depuis le {_fr(start)}"


def _plural(count, word):
    return f"{count} {word}{'s' if count > 1 else ''}"


@dataclasses.dataclass
class Fact:
    label: str
    value: str = ""
    detail: str = ""
    badge_label: str = ""
    badge_classes: str = ""
    # Shown with the platform's own state badge.
    job_application: object = None
    # The page with its details, if any: the label leads there.
    url: str = ""


@dataclasses.dataclass
class Part:
    key: str
    title: str
    icon: str
    summary: str
    facts: list = dataclasses.field(default_factory=list)
    badge_label: str = ""
    badge_classes: str = ""
    link_label: str = ""
    link_url: str = ""

    @property
    def can_open(self):
        return bool(self.facts)


def _approval_part(approval):
    if approval is None:
        return Part("approval", f"PASS{NBSP}IAE", "ri-pass-valid-line", f"Aucun PASS{NBSP}IAE délivré")
    badge_label, badge_tone = APPROVAL_BADGES[approval.state]
    facts = [
        Fact("Numéro", approval.number_with_spaces),
        Fact("Période", _period(approval.start_at, approval.end_at)),
    ]
    if approval.is_valid:
        facts.append(Fact("Reliquat", approval.get_remainder_display()))
    today = timezone.localdate()
    for suspension in approval.suspension_set.all():
        if suspension.start_at <= today <= suspension.end_at:
            facts.append(
                Fact(
                    "Suspension en cours",
                    _period(suspension.start_at, suspension.end_at),
                    detail=suspension.get_reason_display(),
                )
            )
    return Part(
        "approval",
        f"PASS{NBSP}IAE",
        "ri-pass-valid-line",
        _period(approval.start_at, approval.end_at),
        facts,
        badge_label=badge_label,
        badge_classes=_badge(badge_tone),
        link_label=f"Voir le PASS{NBSP}IAE",
        link_url=reverse("approvals:details", kwargs={"public_id": approval.public_id}),
    )


def _eligibility_part(diagnosis, summary):
    if diagnosis is None:
        return Part(
            "eligibility",
            "Diagnostic d’éligibilité",
            "ri-shield-check-line",
            summary,
            [],
            badge_label="Aucun",
            badge_classes=_badge("warning"),
        )
    author = " · ".join(
        name
        for name in [
            diagnosis.author.get_full_name() if diagnosis.author else "",
            diagnosis.author_organization.display_name if diagnosis.author_organization else "",
        ]
        if name
    )
    facts = [
        Fact("Réalisé le", _fr(timezone.localdate(diagnosis.created_at))),
        # An expired diagnosis still counts for the duration of the PASS IAE.
        Fact("Valide jusqu’au" if diagnosis.is_valid else "Expiré le", _fr(diagnosis.expires_at)),
    ]
    if author:
        facts.append(Fact("Par", author))
    return Part(
        "eligibility",
        "Diagnostic d’éligibilité",
        "ri-shield-check-line",
        summary,
        facts,
        # Valid either way; the summary says when it is through the PASS IAE.
        badge_label="Valide",
        badge_classes=_badge("success"),
    )


def _contracts_part(request, job_seeker, contracts):
    latest = sorted(contracts, key=lambda contract: contract.start_date, reverse=True)[:CONTRACTS_SHOWN]
    facts = [
        Fact(
            contract_place(request, contract).capitalize(),
            _period(contract.start_date, contract.end_date),
            badge_label="Terminé" if contract.has_ended else "En cours",
            badge_classes=_badge("muted" if contract.has_ended else "success"),
        )
        for contract in latest
    ]
    return Part(
        "contracts",
        "Contrats",
        "ri-file-text-line",
        _plural(len(contracts), "contrat") if contracts else "Aucun contrat connu",
        facts,
        link_label="Voir les contrats",
        link_url=reverse("job_seekers_views:contracts", kwargs={"public_id": job_seeker.public_id}),
    )


def _job_applications_part(request, job_seeker):
    # Only those whose details the user may see, as the tab shows them.
    job_applications = list(
        _job_applications(request, job_seeker)
        .filter(user_can_see_details=True)
        .select_related("to_company")
        .order_by("-created_at")
    )
    facts = [
        Fact(
            job_application.to_company.display_name,
            detail=f"Envoyée le {_fr(timezone.localdate(job_application.created_at))}",
            job_application=job_application,
            url=_job_application_url(request, job_application),
        )
        for job_application in job_applications[:JOB_APPLICATIONS_SHOWN]
    ]
    return Part(
        "job_applications",
        "Candidatures",
        "ri-file-user-line",
        _plural(len(job_applications), "candidature") if job_applications else "Aucune candidature",
        facts,
        link_label="Voir les candidatures",
        link_url=reverse("job_seekers_views:job_applications", kwargs={"public_id": job_seeker.public_id}),
    )


def _report_part(request, job_seeker):
    reports = ProSupportReport.objects.filter(job_seeker=job_seeker).select_related("company").order_by("-created_at")
    report = next((report for report in reports if can_view_pro_support_report(request, report)), None)
    if report is None:
        return Part(
            "report",
            "Bilan d’accompagnement",
            "ri-file-edit-line",
            "Aucun bilan",
            [],
        )
    facts = [
        Fact("Rempli le", _fr(timezone.localdate(report.created_at))),
        Fact("Fin du contrat", _fr(report.contract_end_date)),
    ]
    if report.company:
        facts.append(Fact("Par", report.company.display_name))
    return Part(
        "report",
        "Bilan d’accompagnement",
        "ri-file-edit-line",
        f"Rempli le {_fr(timezone.localdate(report.created_at))}",
        facts,
        link_label="Lire le bilan",
        link_url=reverse("job_seekers_views:pro_support_report", kwargs={"public_id": report.public_id}),
    )


def _personal_information_part(job_seeker, can_view_personal_information):
    facts = []
    if can_view_personal_information:
        facts = [
            Fact("Téléphone", job_seeker.phone or "Non renseigné"),
            Fact("Adresse e-mail", job_seeker.email or "Non renseignée"),
            Fact("Adresse", job_seeker.address_on_one_line or "Non renseignée"),
        ]
    return Part(
        "personal_information",
        "Informations personnelles",
        "ri-user-line",
        job_seeker.email if can_view_personal_information and job_seeker.email else "Masquées pour vous",
        facts,
        link_label="Voir la fiche complète",
        link_url=reverse("job_seekers_views:details", kwargs={"public_id": job_seeker.public_id}),
    )


def file_parts(
    request,
    job_seeker,
    *,
    approval,
    iae_eligibility_diagnosis,
    eligibility_summary,
    contracts,
    can_view_contracts,
    can_view_report,
    can_view_personal_information,
):
    """The parts of the file the user may see, each with the scope of the tab it leads to."""
    parts = []
    if request.from_iae_actor:
        parts += [_approval_part(approval), _eligibility_part(iae_eligibility_diagnosis, eligibility_summary)]
    if can_view_contracts:
        parts.append(_contracts_part(request, job_seeker, contracts))
    parts.append(_job_applications_part(request, job_seeker))
    if can_view_report:
        parts.append(_report_part(request, job_seeker))
    parts.append(_personal_information_part(job_seeker, can_view_personal_information))
    return parts
