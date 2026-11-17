"""The job seeker's barriers, gathered from what the platform records, in three columns.

- The pro support reports name the barriers a company identified at the end of a contract. The latest one fills
  « À travailler »; a barrier of the report before it that the latest one no longer names is « Levé ».
- The administrative criteria of the eligibility diagnoses (IAE, and GEIQ for prescribers) hint at barriers:
  shown as signals to confirm, a certified criterion marked as such. Weak hints (ZRR, education level) are left out.
- The pending or accepted orientations towards a service whose data·inclusion thematic matches a barrier put it
  « En cours ». Housing has no barrier of its own in the reports: it goes with the personal or family situation.

Each source keeps the scope of the matching part of the existing job seeker page: the reports the user may read,
the eligibility diagnosis they see there, the orientations of the orientations tab.
"""

import dataclasses

from django.urls import reverse
from django.utils import timezone

from itou.companies.enums import ProSupportReportBarrier
from itou.eligibility.enums import AdministrativeCriteriaKind as Kind
from itou.eligibility.models.geiq import GEIQEligibilityDiagnosis
from itou.insertion.enums import OrientationStatus
from itou.users.perms import can_view_pro_support_report
from itou.www.next_steps_views.advisors import visible_orientations


Barrier = ProSupportReportBarrier
OTHER = "OTHER"
NBSP = " "

CRITERIA_BARRIERS = {
    Kind.PM: [Barrier.MOBILITY],
    Kind.TH: [Barrier.HEALTH],
    Kind.AAH: [Barrier.HEALTH, Barrier.FINANCIAL],
    Kind.RSA: [Barrier.FINANCIAL],
    Kind.ASS: [Barrier.FINANCIAL],
    Kind.MINIMA: [Barrier.FINANCIAL],
    Kind.AUTRE_MINIMA: [Barrier.FINANCIAL],
    Kind.PI: [Barrier.FAMILY],
    Kind.ASE: [Barrier.FAMILY],
    Kind.PSH_PR: [Barrier.FAMILY],
    Kind.REF_DA: [Barrier.LEGAL],
    Kind.RS_PS_DA: [Barrier.LEGAL],
    Kind.DETENTION_MJ: [Barrier.LEGAL],
    Kind.FLE: [Barrier.LITERACY],
}

# data·inclusion thematics, by their prefix.
THEMATIC_BARRIERS = {
    "mobilite": Barrier.MOBILITY,
    "sante": Barrier.HEALTH,
    "famille": Barrier.FAMILY,
    "logement-hebergement": Barrier.FAMILY,
    "difficultes-financieres": Barrier.FINANCIAL,
    "equipement-et-alimentation": Barrier.FINANCIAL,
    "numerique": Barrier.DIGITAL,
    "difficultes-administratives-ou-juridiques": Barrier.LEGAL,
    "lecture-ecriture-calcul": Barrier.LITERACY,
}

ONGOING_ORIENTATIONS = [OrientationStatus.PENDING, OrientationStatus.ACCEPTED]


def _fr(date):
    return f"{timezone.localdate(date):%d/%m/%Y}"


@dataclasses.dataclass
class Clue:
    """Where a barrier comes from."""

    # report, criterion, orientation, lifted (CSS modifiers and icons)
    kind: str
    text: str
    certified: bool = False
    url: str = ""

    @property
    def icon(self):
        return {
            "report": "ri-file-list-3-line",
            "criterion": "ri-shield-check-line",
            "orientation": "ri-signpost-line",
            "lifted": "ri-checkbox-circle-line",
        }[self.kind]


@dataclasses.dataclass
class Card:
    key: str
    label: str
    clues: list = dataclasses.field(default_factory=list)
    in_progress: bool = False

    @property
    def to_confirm(self):
        # Only hinted at by the eligibility criteria.
        return all(clue.kind == "criterion" for clue in self.clues)


@dataclasses.dataclass
class Barriers:
    to_work: list
    in_progress: list
    lifted: list
    # The latest report, if any: the section says when it was filled.
    report: object = None

    @property
    def empty(self):
        return not (self.to_work or self.in_progress or self.lifted)


def _reports(request, job_seeker):
    reports = job_seeker.pro_support_reports.select_related("company").order_by("-created_at")
    if request.from_employer:
        reports = reports.filter(company=request.current_organization)
    return [report for report in reports[:2] if can_view_pro_support_report(request, report)]


def _report_text(report):
    by = f" · {report.company.display_name}" if report.company else ""
    return f"Bilan d’accompagnement du {_fr(report.created_at)}{by}"


def _diagnoses(request, job_seeker, iae_eligibility_diagnosis):
    """The diagnoses the job seeker page shows the user, with their name."""
    diagnoses = []
    if iae_eligibility_diagnosis:
        diagnoses.append(("IAE", iae_eligibility_diagnosis))
    if request.from_prescriber:
        geiq = GEIQEligibilityDiagnosis.objects.valid_diagnoses_for(job_seeker).first()
        if geiq:
            diagnoses.append(("GEIQ", geiq))
    return diagnoses


def gather_barriers(request, job_seeker, iae_eligibility_diagnosis=None):
    cards = {}

    def card(key):
        if key not in cards:
            label = Barrier(key).label if key != OTHER else "Autres freins"
            cards[key] = Card(key, label)
        return cards[key]

    reports = _reports(request, job_seeker)
    latest = reports[0] if reports else None
    lifted = []
    if latest:
        for key in latest.barriers:
            card(key).clues.append(Clue("report", _report_text(latest)))
        if latest.other_barrier:
            card(OTHER).clues.append(Clue("report", f"{latest.other_barrier} · {_report_text(latest)}"))
        if len(reports) > 1:
            previous = reports[1]
            for key in previous.barriers:
                if key not in latest.barriers:
                    lifted.append(
                        Card(
                            key,
                            Barrier(key).label,
                            [
                                Clue(
                                    "lifted",
                                    f"Noté dans le bilan du {_fr(previous.created_at)}, "
                                    f"plus dans celui du {_fr(latest.created_at)}",
                                )
                            ],
                        )
                    )
    lifted_keys = {lifted_card.key for lifted_card in lifted}

    for name, diagnosis in _diagnoses(request, job_seeker, iae_eligibility_diagnosis):
        for selected in diagnosis.selected_administrative_criteria.select_related("administrative_criteria"):
            criterion = selected.administrative_criteria
            for key in CRITERIA_BARRIERS.get(criterion.kind, []):
                if key in lifted_keys:
                    # The latest report says otherwise, and it is more recent than the criteria.
                    continue
                card(key).clues.append(
                    Clue(
                        "criterion",
                        f"Critère «{NBSP}{criterion.name}{NBSP}», "
                        f"diagnostic d’éligibilité {name} du {_fr(diagnosis.created_at)}",
                        certified=selected.certified_at is not None,
                    )
                )

    orientations = (
        visible_orientations(request, job_seeker)
        .filter(status__in=ONGOING_ORIENTATIONS)
        .select_related("service")
        .prefetch_related("service__thematics")
        .order_by("-created_at")
    )
    for orientation in orientations:
        keys = {
            THEMATIC_BARRIERS[prefix]
            for thematic in orientation.service.thematics.all()
            if (prefix := thematic.value.split("--")[0]) in THEMATIC_BARRIERS
        }
        url = ""
        if orientation.user_can_see_details:
            url = reverse("insertion_views:orientation_details_for_sender", kwargs={"orientation_id": orientation.pk})
        for key in keys:
            card(key).in_progress = True
            card(key).clues.insert(
                0,
                Clue(
                    "orientation",
                    f"Orientation vers «{NBSP}{orientation.service.name}{NBSP}» du {_fr(orientation.created_at)} · "
                    f"{orientation.get_status_display()}",
                    url=url,
                ),
            )

    order = [*Barrier.values, OTHER]
    ordered = sorted(cards.values(), key=lambda card: order.index(card.key))
    return Barriers(
        to_work=[card for card in ordered if not card.in_progress and card.key not in lifted_keys],
        in_progress=[card for card in ordered if card.in_progress],
        lifted=[card for card in lifted if card.key not in {c.key for c in ordered if c.in_progress}],
        report=latest,
    )
