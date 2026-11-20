"""Guided journeys of the "Prochaines étapes" experiment.

A journey runs an action step by step in a side drawer: the existing forms of the platform, split into steps, with a
stepper, then a confirmation screen. The data is saved by the same forms and model methods as the existing screens,
so validation, permissions and side effects (notifications, follow-up) stay the same.

The steps keep no state on the server: the answers of the other steps travel as hidden fields, and every form is
validated again, in full, before anything is saved. Without JavaScript, a journey is an ordinary page.

When a decision needs a long existing wizard (hiring, refusing an application), the journey hands over to it.
"""

import dataclasses
import logging
import urllib.parse
import uuid

from django import forms
from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.template import loader
from django.urls import reverse
from django.utils import timezone
from django_xworkflows import models as xwf_models

from itou.approvals.enums import ProlongationRequestDenyReason, ProlongationRequestStatus
from itou.approvals.models import (
    Approval,
    Prolongation,
    ProlongationRequest,
    ProlongationRequestDenyInformation,
)
from itou.asp.forms import BirthPlaceWithBirthdateModelForm, BirthPlaceWithoutBirthdateModelForm
from itou.asp.models import Country
from itou.common_apps.address.forms import JobSeekerAddressForm
from itou.companies.enums import CompanyKind, ContractType, ProSupportReportAutonomy, ProSupportReportBarrier
from itou.companies.models import ProSupportReport
from itou.eligibility.enums import AuthorKind
from itou.eligibility.models.iae import EligibilityDiagnosis, get_criteria_from_job_seeker
from itou.insertion.models import Service
from itou.insertion.utils import get_missing_orientation_beneficiary_field_labels
from itou.job_applications.enums import JobApplicationState, RefusalReason, SenderKind
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.next_steps.models import BarrierStatus, JobSeekerBarrier
from itou.prescribers.enums import PrescriberAuthorizationStatus
from itou.rdv_insertion.models import InvitationRequest
from itou.users.enums import ActionKind, UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.users.perms import can_fill_pro_support_report, can_orient_towards_insertion_service
from itou.utils.constants import ITOU_DIAGNOSTIC_URL
from itou.utils.db import (
    ExclusionViolationError,
    UniqueViolationError,
    maybe_exclusion_violation,
    maybe_unique_violation,
)
from itou.utils.perms.utils import can_edit_personal_information, can_view_personal_information
from itou.utils.widgets import DuetDatePickerWidget
from itou.www.apply.forms import (
    AcceptForm,
    AnswerForm,
    BirthDateForm,
    JobApplicationRefusalJobSeekerAnswerForm,
    JobApplicationRefusalPrescriberAnswerForm,
    JobApplicationRefusalReasonForm,
    JobSeekerPersonalDataForm,
)
from itou.www.apply.views.batch_views import _get_and_lock_received_applications, _get_recruitment_to_close
from itou.www.approvals_views.forms import (
    ProlongationRequestDenyInformationProposedActionsForm,
    ProlongationRequestDenyInformationReasonExplanationForm,
    ProlongationRequestDenyInformationReasonForm,
    SuspensionForm,
)
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.insertion_views.forms import (
    OrientationConformityForm,
    OrientationDocumentsForm,
    OrientationReferentForm,
)
from itou.www.insertion_views.views import create_orientation
from itou.www.job_seekers_views.forms import ProSupportReportForm
from itou.www.job_seekers_views.views import (
    PRO_SUPPORT_REQUEST_CONTRACT_ENDED,
    PRO_SUPPORT_REQUEST_CONTRACT_ENDING_SOON,
    PRO_SUPPORT_REQUEST_EMAIL_BODY,
    PRO_SUPPORT_REQUEST_EMAIL_SUBJECT,
    _pro_support_request_company_email,
)
from itou.www.next_steps_views.barriers import BARRIER_ICONS, CRITERIA_BARRIERS
from itou.www.next_steps_views.period_bar import approval_bar, prolongation_bar, suspension_bar


logger = logging.getLogger(__name__)

NBSP = " "
PASS_IAE = f"PASS{NBSP}IAE"
FIELDS_TEMPLATE = "next_steps/journeys/fields.html"
FACTS_TEMPLATE = "next_steps/journeys/facts.html"
RECAP_TEMPLATE = "next_steps/journeys/recap.html"
CRITERIA_LEVELS = [(1, AdministrativeCriteriaForm.LEVEL_1_PREFIX), (2, AdministrativeCriteriaForm.LEVEL_2_PREFIX)]


def _fr(date):
    if hasattr(date, "hour"):
        date = timezone.localdate(date)
    return f"{date:%d/%m/%Y}"


@dataclasses.dataclass
class Show:
    """How a field is shown, as in the prototype: "options" (one card per choice), "select" or "default"."""

    kind: str = "default"
    # For options: value -> (title, or None to keep the choice's label; description, or None).
    choices: dict = dataclasses.field(default_factory=dict)
    # Show the field's label above the cards, when the step's question does not already ask for it.
    legend: bool = False


DEFAULT_SHOW = Show()


@dataclasses.dataclass
class Box:
    """Context shown in a step: a motif, what a choice entails, who receives what."""

    text: str
    title: str = ""
    # "", "warn" or "ok".
    variant: str = ""


@dataclasses.dataclass
class Step:
    label: str
    # The form this step shows, by key in Journey.build_forms(), and which of its fields (None: all of them).
    form: str | tuple | None = None
    fields: list | None = None
    template: str = FIELDS_TEMPLATE
    submit_label: str = "Continuer"
    # A step that hands over to an existing screen instead of submitting: (label, url).
    handover: tuple | None = None
    # Whether the step's template shows the journey's facts itself, instead of above the question.
    facts_in_template: bool = False
    # The question the step asks, a hint below it, how its fields are shown, and context boxes.
    question: str = ""
    hint: str = ""
    layout: dict = dataclasses.field(default_factory=dict)
    boxes: list = dataclasses.field(default_factory=list)
    # A period bar (see period_bar.py), shown under the question.
    bar: object = None
    # Whether the step sends files: its form is then multipart.
    files: bool = False

    def __post_init__(self):
        if self.template in (FACTS_TEMPLATE, "next_steps/journeys/application.html"):
            self.facts_in_template = True


@dataclasses.dataclass
class Summary:
    """Who the person is, for a professional who follows hundreds: why they are asked, and what links them to them.

    Shown at the top of the first step, in a box, with a link to the job seeker's page in a new tab: the drawer often
    opens from « À faire », without the page behind it.
    """

    title: str
    lines: list
    url: str = ""


@dataclasses.dataclass
class Result:
    title: str
    lines: list
    # An optional main link: (label, url).
    link: tuple | None = None
    # An optional period bar (see period_bar.py).
    bar: object = None


class Journey:
    title = ""
    job_seeker = None

    def __init__(self, request, pk):
        self.request = request
        self.load(pk)

    def load(self, pk):
        """Fetch the objects and check the user may act: raise Http404 otherwise."""
        raise NotImplementedError

    def facts(self):
        return []

    def identity(self):
        """A line under the person's name in the drawer's header, on every step, to recognize them: "" for none."""
        return ""

    def summary(self):
        """A Summary at the top of the first step, or None."""
        return None

    def build_forms(self, data=None, initial=None):
        """Forms by key: bound to data to validate, or unbound with initial values to display."""
        return {}

    def steps(self, data):
        raise NotImplementedError

    def steps_known(self, data):
        """Whether the steps are all known yet: some depend on an answer to come."""
        return True

    def recap(self, forms):
        """(label, value) pairs shown on a confirmation step."""
        return []

    def context(self):
        return {}

    def done(self, forms):
        raise NotImplementedError


class DecisionForm(forms.Form):
    decision = forms.ChoiceField(label="Votre décision", widget=forms.RadioSelect)

    def __init__(self, *args, choices, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["decision"].choices = choices


def _label(form, field_name, value):
    labels = {}
    for key, label in form.fields[field_name].choices:
        if isinstance(label, list | tuple):  # A group of choices
            labels |= {str(sub_key): sub_label for sub_key, sub_label in label}
        else:
            labels[str(key)] = label
    # Submitted values are strings, choice values may not be.
    return labels[str(value)]


# Employers
# ------------------------------------------------------------------------------


class ProSupportReportFillJourney(Journey):
    title = "Remplir le bilan d’accompagnement"

    def load(self, pk):
        request = self.request
        if not can_fill_pro_support_report(request):
            raise Http404
        company = request.current_organization
        self.job_seeker = get_object_or_404(
            User.objects.at_end_of_journey(siae=company), public_id=pk, kind=UserKind.JOB_SEEKER
        )
        self.contract = self.job_seeker.contracts.filter(company=company).order_by("-start_date", "-pk").first()
        # Same rules as job_seekers_views.create_pro_support_report.
        if self.contract is None or ProSupportReport.objects.filter(contract=self.contract).exists():
            raise Http404

    def facts(self):
        ended = self.contract.has_ended
        return [("Contrat terminé le" if ended else "Fin du contrat", _fr(self.contract.end_date))]

    def build_forms(self, data=None, initial=None):
        request = self.request
        form = ProSupportReportForm(
            request.path,
            data=data,
            initial=initial,
            instance=ProSupportReport(
                job_seeker=self.job_seeker,
                company=request.current_organization,
                author=request.user,
                contract=self.contract,
                contract_end_date=self.contract.end_date,
            ),
        )
        # Here the follow-up question comes as the next step, not by reloading the form.
        form.fields["has_solution"].widget.attrs = {}
        return {"report": form}

    def _report_recipient(self):
        """Who will receive the report: same query as ProSupportReport.notify_authorized_prescriber."""
        assignment = (
            JobSeekerAssignment.objects.filter(
                job_seeker=self.job_seeker,
                prescriber_organization__authorization_status=PrescriberAuthorizationStatus.VALIDATED,
            )
            .select_related("professional", "prescriber_organization")
            .order_by("-last_action_at")
            .first()
        )
        if assignment is None:
            return Box("Aucun prescripteur habilité ne suit la personne : le bilan restera consultable sur sa fiche.")
        return Box(
            f"Le bilan sera envoyé à {assignment.professional.get_full_name()} "
            f"({assignment.prescriber_organization.display_name}), le dernier prescripteur habilité "
            "qui a accompagné la personne."
        )

    def steps(self, data):
        if data.get("has_solution") == "False":
            follow_up = Step(
                "Orientation",
                "report",
                ["orientation"],
                question="Quelle orientation serait la plus adaptée ?",
                layout={"orientation": Show("options")},
            )
        else:
            follow_up = Step(
                "Solution",
                "report",
                ["solution"],
                question="Quelle solution est envisagée ?",
                layout={"solution": Show("options")},
            )
        return [
            Step(
                "Freins",
                "report",
                ["barriers", "other_barrier"],
                question="Quels freins restent à travailler ?",
                hint="Ne cochez rien si aucun frein n’a été identifié.",
                layout={"barriers": Show("options")},
            ),
            Step(
                "Autonomie",
                "report",
                ["autonomy"],
                question="Son autonomie dans la recherche d’emploi",
                layout={
                    "autonomy": Show(
                        "options",
                        {
                            str(level.value): (f"{level.value} sur 5", level.label)
                            for level in ProSupportReportAutonomy
                        },
                    )
                },
            ),
            Step(
                "La suite",
                "report",
                ["has_solution"],
                question="Une solution est-elle déjà prévue après le contrat ?",
                hint="Un bilan comporte soit une solution envisagée, soit une orientation.",
                layout={
                    "has_solution": Show(
                        "options",
                        {
                            "True": (None, "Emploi, formation, renouvellement…"),
                            "False": (None, "Vous indiquerez l’accompagnement le plus adapté."),
                        },
                    )
                },
            ),
            follow_up,
            Step(
                "Envoi",
                "report",
                [],
                template=RECAP_TEMPLATE,
                submit_label="Envoyer le bilan",
                question="Vérifiez avant d’envoyer",
                boxes=[self._report_recipient()],
            ),
        ]

    def recap(self, forms):
        form = forms["report"]
        report = form.cleaned_data
        barriers = [_label(form, "barriers", barrier) for barrier in report["barriers"]]
        lines = [("Freins", ", ".join(barriers) or "Aucun frein identifié")]
        if report.get("other_barrier"):
            lines.append(("Autres freins identifiés", report["other_barrier"]))
        lines.append(("Autonomie", f"{report['autonomy']} sur 5"))
        if report.get("solution"):
            lines.append(("Solution envisagée", _label(form, "solution", report["solution"])))
        else:
            lines.append(("Orientation", _label(form, "orientation", report["orientation"])))
        return lines

    def done(self, forms):
        request = self.request
        # Same as job_seekers_views.create_pro_support_report.
        report = forms["report"].save()
        report.notify_authorized_prescriber()
        JobSeekerAssignment.objects.upsert_assignment(
            self.job_seeker, request.user, request.current_organization, ActionKind.FILL_REPORT
        )
        if report.notified_prescriber:
            sent_to = f"Il est transmis par e-mail à {report.notified_prescriber.get_full_name()}."
        else:
            sent_to = "Aucun prescripteur habilité ne suit la personne pour le moment."
        return Result(
            title="Bilan envoyé",
            lines=[sent_to, "Il reste consultable sur la fiche de la personne et ne peut plus être modifié."],
        )


class SuspensionJourney(Journey):
    title = f"Suspendre le {PASS_IAE}"

    def load(self, pk):
        request = self.request
        if not request.from_employer:
            raise Http404
        self.company = request.current_organization
        # Same rules as approvals_views.suspend.
        self.approval = get_object_or_404(
            Approval.objects.filter(
                Exists(
                    JobApplication.objects.filter(
                        approval=OuterRef("pk"), to_company=self.company, state=JobApplicationState.ACCEPTED
                    )
                )
            ).select_related("user"),
            pk=pk,
        )
        if not self.approval.can_be_suspended_by_siae(self.company):
            raise Http404
        self.job_seeker = self.approval.user

    def facts(self):
        return [
            (PASS_IAE, self.approval.number_with_spaces),
            ("Fin prévue", _fr(self.approval.end_at)),
            ("Reliquat", self.approval.get_remainder_display()),
        ]

    def build_forms(self, data=None, initial=None):
        return {"suspension": SuspensionForm(approval=self.approval, siae=self.company, data=data, initial=initial)}

    def steps(self, data):
        contract = self.job_seeker.contracts.filter(company=self.company).order_by("-start_date", "-pk").first()
        hint = f"La suspension arrête le décompte des jours du {PASS_IAE}."
        if contract and contract.end_date and contract.has_ended:
            hint = f"Le contrat est terminé depuis le {_fr(contract.end_date)}. " + hint
        # The bar of the confirmation step shows the suspension once its dates are valid.
        suspension_form = self.build_forms(data=data)["suspension"] if data else None
        recap_bar = None
        if suspension_form is not None and suspension_form.is_valid():
            recap_bar = suspension_bar(
                self.approval, suspension_form.cleaned_data["start_at"], suspension_form.cleaned_data["end_at"]
            )
        return [
            Step(
                "La suspension",
                "suspension",
                hint=hint,
                bar=approval_bar(self.approval, contract_end=contract.end_date if contract else None),
                layout={
                    "set_default_end_date": Show("options"),
                    "reason": Show("options", legend=True),
                },
            ),
            Step(
                "Vérifier",
                "suspension",
                [],
                template=RECAP_TEMPLATE,
                submit_label="Suspendre",
                question="Vérifiez avant de suspendre",
                bar=recap_bar,
            ),
        ]

    def recap(self, forms):
        form = forms["suspension"]
        suspension = form.cleaned_data
        # The dates are on the strip above.
        lines = [("Motif", _label(form, "reason", suspension["reason"]))]
        if suspension.get("reason_explanation"):
            lines.append(("Explications", suspension["reason_explanation"]))
        return lines

    def done(self, forms):
        previous_end = self.approval.end_at
        # Same as approvals_views.suspend.
        suspension = forms["suspension"].save(commit=False)
        suspension.created_by = self.request.user
        suspension.save()
        logger.info(
            "user=%s created suspension=%s (approval=%s) from %s to %s",
            self.request.user.pk,
            suspension.pk,
            self.approval.pk,
            suspension.start_at,
            suspension.end_at,
        )
        self.approval.refresh_from_db()
        return Result(
            title=f"{PASS_IAE} suspendu",
            lines=[
                f"Du {_fr(suspension.start_at)} au {_fr(suspension.end_at)}, "
                f"motif{NBSP}: {suspension.get_reason_display()}.",
                f"Sa date de fin passe au {_fr(self.approval.end_at)}.",
            ],
            bar=suspension_bar(self.approval, suspension.start_at, suspension.end_at, approval_end=previous_end),
        )


class JobApplicationJourney(Journey):
    """Answer an application: processing, postponed, refused or hired, each with the steps of the existing screens.

    Refusing reuses the forms and the rules of apply.views.batch_views.RefuseWizardView, for one application.
    Hiring reuses those of apply.views.accept_views and common: the job seeker's missing information, the contract,
    the employer's eligibility diagnosis when needed, then the confirmation. GEIQ hiring, with its own diagnosis and
    contract fields, and a company under a posteriori control sanction, still use the existing screens.
    """

    title = "Répondre à la candidature"

    def load(self, pk):
        request = self.request
        if not request.from_employer:
            raise Http404
        self.company = request.current_organization
        self.job_application = get_object_or_404(
            JobApplication.objects.is_active_company_member(request.user)
            .visible_by_employers()
            .filter(to_company=self.company)
            .select_related(
                "job_seeker",
                "job_seeker__jobseeker_profile",
                "to_company",
                "sender",
                "sender_prescriber_organization",
                "sender_company",
            )
            .prefetch_related("selected_jobs__appellation"),
            pk=pk,
        )
        self.job_seeker = self.job_application.job_seeker
        self.eligibility_diagnosis = None
        if self.company.is_subject_to_iae_rules:
            self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(
                self.job_seeker, self.company
            )
        # Same rule as apply.views.accept_views.check_waiting_period.
        self.blocked_by_waiting_period = self.job_seeker.new_approval_blocked_by_waiting_period(
            siae=self.company, sender_prescriber_organization=self.job_application.sender_prescriber_organization
        )
        self.hiring_in_drawer = self.company.kind != CompanyKind.GEIQ and not (
            self.company.is_subject_to_iae_rules and self.company.get_active_suspension_text_with_dates()
        )

    def _sender_display(self):
        job_application = self.job_application
        if job_application.sender_kind == SenderKind.JOB_SEEKER:
            return "La personne elle-même"
        organization = job_application.sender_prescriber_organization or job_application.sender_company
        names = [job_application.sender.get_full_name() if job_application.sender else None]
        names.append(organization.display_name if organization else None)
        return ", ".join(name for name in names if name)

    def facts(self):
        job_application = self.job_application
        jobs = [job_description.display_name for job_description in job_application.selected_jobs.all()]
        return [
            ("Reçue le", _fr(job_application.created_at)),
            ("Envoyée par", self._sender_display()),
            ("Poste" if len(jobs) == 1 else "Postes", ", ".join(jobs) or "Candidature spontanée"),
            ("Statut", job_application.get_state_display()),
        ]

    def _application_boxes(self):
        """What to know before answering: an earlier contract with the company, and the eligibility."""
        boxes = []
        contracts = list(self.job_seeker.contracts.filter(company=self.company).order_by("-start_date"))
        if contracts:
            last = contracts[0]
            text = f"Contrat du {_fr(last.start_date)}" + (f" au {_fr(last.end_date)}" if last.end_date else "")
            if len(contracts) > 1:
                text += f", et {len(contracts) - 1} contrat{'s' if len(contracts) > 2 else ''} avant."
            boxes.append(Box(text, title="Déjà en contrat chez vous"))
        if not self.company.is_subject_to_iae_rules:
            return boxes
        approval = self.job_seeker.latest_approval
        diagnosis = self.eligibility_diagnosis
        if self.job_seeker.has_valid_approval:
            boxes.append(
                Box(
                    f"Valide jusqu’au {_fr(approval.end_at)}. L’embauche ne demande pas de nouveau diagnostic.",
                    title=f"{PASS_IAE} {approval.number_with_spaces}",
                    variant="ok",
                )
            )
        elif self.blocked_by_waiting_period:
            # Same rule as apply.views.accept_views.check_waiting_period: hiring is not offered.
            boxes.append(
                Box(
                    f"Son {PASS_IAE} a expiré le {_fr(approval.end_at)}. Jusqu’au {_fr(approval.waiting_period_end)}, "
                    "seul un prescripteur habilité peut valider à nouveau son éligibilité.",
                    title="Éligibilité à revalider",
                    variant="warn",
                )
            )
        elif diagnosis and diagnosis.is_considered_valid:
            author = diagnosis.author_organization.display_name if diagnosis.author_organization else None
            boxes.append(
                Box(
                    (f"Par {author}, " if author else "")
                    + f"valable jusqu’au {_fr(diagnosis.considered_to_expire_at)}.",
                    title="Éligibilité validée",
                    variant="ok",
                )
            )
        else:
            boxes.append(
                Box(
                    f"Aucun diagnostic valide{NBSP}: vous sélectionnerez les critères administratifs "
                    "au moment d’embaucher.",
                    title="Éligibilité à établir",
                    variant="warn",
                )
            )
        return boxes

    def steps_known(self, data):
        return bool(data.get("decision"))

    def _choices(self):
        job_application = self.job_application
        choices = []
        if job_application.process.is_available():
            choices.append(("process", "La mettre à l’étude"))
        if job_application.postpone.is_available():
            choices.append(("postpone", "La mettre en attente, avec un message"))
        if job_application.accept.is_available() and not self.blocked_by_waiting_period:
            choices.append(("accept", "Accepter l’embauche"))
        if job_application.refuse.is_available():
            choices.append(("refuse", "Décliner la candidature"))
        return choices

    def _job_seeker_info_forms(self, data, initial):
        """Same forms as apply.views.common.CommonUserInfoFormsMixin: only the missing information is asked."""
        job_seeker, profile = self.job_seeker, self.job_seeker.jobseeker_profile
        initial = initial or {}  # These forms merge it with their own initial values.
        forms = {}
        personal_data = JobSeekerPersonalDataForm(
            instance=job_seeker, initial=initial, data=data, back_url=self.request.path
        )
        if personal_data.fields:
            forms["personal_data"] = personal_data
        birth_data_kwargs = {"instance": profile, "initial": initial, "data": data}
        birth_data_class = None
        if profile.birthdate:
            if not profile.birth_country:
                birth_data_class = BirthPlaceWithoutBirthdateModelForm
                birth_data_kwargs["birthdate"] = profile.birthdate
        elif profile.birth_country_id and profile.birth_country_id != Country.FRANCE_ID:
            birth_data_class = BirthDateForm
        else:
            birth_data_class = BirthPlaceWithBirthdateModelForm
        if birth_data_class:
            forms["birth_data"] = birth_data_class(**birth_data_kwargs)
        if not job_seeker.address_on_one_line:
            forms["user_address"] = JobSeekerAddressForm(instance=job_seeker, initial=initial, data=data)
        return forms

    def build_forms(self, data=None, initial=None):
        job_applications = [self.job_application]
        refusal_initial = initial
        if initial is not None and not initial.get("job_seeker_answer") and initial.get("refusal_reason"):
            refusal_initial = initial | {"job_seeker_answer": self._refusal_message(initial["refusal_reason"])}
        criteria_initial = initial
        if initial is None and self.job_seeker.last_checked_at > timezone.now() - timezone.timedelta(hours=24):
            # Same initial criteria as eligibility_views.BaseIAEEligibilityViewForEmployer.
            criteria_initial = {"administrative_criteria": get_criteria_from_job_seeker(self.job_seeker)}
        return {
            "decision": DecisionForm(data=data, initial=initial, choices=self._choices()),
            "answer": AnswerForm(data=data, initial=initial),
            "refusal_reason": JobApplicationRefusalReasonForm(job_applications, data=data, initial=initial),
            "job_seeker_answer": JobApplicationRefusalJobSeekerAnswerForm(
                job_applications, data=data, initial=refusal_initial
            ),
            "prescriber_answer": JobApplicationRefusalPrescriberAnswerForm(
                job_applications, data=data, initial=initial
            ),
            **self._job_seeker_info_forms(data, initial),
            "accept": AcceptForm(
                instance=self.job_application,
                company=self.company,
                job_seeker=self.job_seeker,
                iae_eligibility_diagnosis=self.eligibility_diagnosis,
                current_user=self.request.user,
                data=data,
                initial=initial,
            ),
            "criteria": AdministrativeCriteriaForm(
                is_authorized_prescriber=False, siae=self.company, data=data, initial=criteria_initial
            ),
        }

    def _refusal_message(self, refusal_reason):
        """Same default message as apply.views.batch_views.RefuseWizardView."""
        if refusal_reason not in RefusalReason.values:
            return ""
        return loader.render_to_string(
            f"apply/refusal_messages/{refusal_reason}.txt",
            context={"to_company": self.company} if refusal_reason == RefusalReason.NON_ELIGIBLE else {},
            request=self.request,
        )

    def _iae_eligibility_needed(self, data):
        """Same rule as apply.views.common.IsIAEEligibilityDiagnosisNeededMixin."""
        if not self.company.is_subject_to_iae_rules or self.job_seeker.has_valid_approval:
            return False
        diagnosis = self.eligibility_diagnosis
        if diagnosis is None:
            return True
        if diagnosis.author_kind == AuthorKind.PRESCRIBER:
            return False
        field = forms.DateField(input_formats=[DuetDatePickerWidget.INPUT_DATE_FORMAT], required=False)
        try:
            hiring_start_at = field.clean(data.get("hiring_start_at")) or timezone.localdate()
        except forms.ValidationError:
            hiring_start_at = timezone.localdate()
        return not diagnosis.expires_at > hiring_start_at

    def steps(self, data):
        pk = self.job_application.pk
        decision_choices = {
            "process": (None, f"Statut{NBSP}: {JobApplicationState.PROCESSING.label}"),
            "postpone": (None, f"Statut{NBSP}: {JobApplicationState.POSTPONED.label}, avec un message"),
            "accept": (None, "Le contrat, puis la confirmation de l’embauche"),
            "refuse": (None, f"Statut{NBSP}: {JobApplicationState.REFUSED.label}, avec un motif et un message"),
        }
        steps = [
            # As in the prototype: what to know before answering, then the answer.
            Step(
                "La candidature",
                template="next_steps/journeys/application.html",
                question="Ce qu’il faut savoir avant de répondre",
                boxes=self._application_boxes(),
            ),
            Step(
                "Votre réponse",
                "decision",
                question="Votre réponse",
                layout={"decision": Show("options", decision_choices)},
            ),
        ]
        match data.get("decision"):
            case "postpone":
                steps.append(
                    Step(
                        "Message",
                        "answer",
                        submit_label="Mettre en attente",
                        question="Votre message",
                        hint="Il sera visible par l’usager et le prescripteur.",
                    )
                )
            case "refuse":
                job_descriptions, close_spontaneous_applications = _get_recruitment_to_close(
                    self.company, [self.job_application]
                )
                closed = [f"la fiche de poste {job_description.display_name}" for job_description in job_descriptions]
                if close_spontaneous_applications:
                    closed.append("toutes les candidatures spontanées")
                steps += [
                    Step(
                        "Motif",
                        "refusal_reason",
                        question="Pourquoi déclinez-vous la candidature ?",
                        layout={
                            "refusal_reason": Show("select"),
                            "refusal_reason_shared_with_job_seeker": Show("options"),
                        },
                        boxes=[
                            Box(
                                f"La réception des candidatures sera désactivée pour {', '.join(closed)}.",
                                title=f"Avec le motif «{NBSP}{RefusalReason.NO_POSITION.label}{NBSP}»",
                                variant="warn",
                            )
                        ]
                        if closed
                        else [],
                    ),
                    Step(
                        "Message à l’usager",
                        "job_seeker_answer",
                        question="Votre message à l’usager",
                        hint="Il est pré-rempli d’après le motif choisi. Vous pouvez le modifier.",
                    ),
                ]
                # Same condition as apply.views.batch_views.RefuseWizardView.get_steps.
                if self.job_application.sender_kind == SenderKind.PRESCRIBER:
                    # Same wording as the existing screen: an orienter is not an authorized prescriber.
                    recipient = (
                        "au prescripteur" if self.job_application.is_sent_by_authorized_prescriber else "à l’orienteur"
                    )
                    steps.append(
                        Step(
                            f"Message {recipient}",
                            "prescriber_answer",
                            question=f"Votre message {recipient}",
                            hint="Il n’est pas communiqué à l’usager.",
                        )
                    )
                steps[-1].submit_label = "Décliner la candidature"
            case "accept" if not self.hiring_in_drawer:
                url = reverse("apply:start-accept", kwargs={"job_application_id": pk})
                steps.append(
                    Step(
                        "Embauche",
                        handover=("Commencer l’embauche", url),
                        question="L’embauche se poursuit sur l’écran habituel",
                        hint="Elle demande des informations propres à votre structure.",
                    )
                )
            case "accept":
                info_forms = tuple(self._job_seeker_info_forms(None, None))
                if info_forms:
                    steps.append(
                        Step(
                            "Usager",
                            info_forms,
                            template="next_steps/journeys/job_seeker_infos.html",
                            question="Informations à compléter",
                            hint="Elles manquent sur son profil et sont nécessaires à l’embauche.",
                        )
                    )
                steps.append(
                    Step(
                        "Contrat",
                        "accept",
                        template="next_steps/journeys/contract.html",
                        question="Le contrat",
                    )
                )
                if self._iae_eligibility_needed(data):
                    steps.append(
                        Step(
                            "Éligibilité",
                            "criteria",
                            template="next_steps/journeys/criteria.html",
                            question="Quels critères administratifs la personne remplit-elle ?",
                            hint=(
                                "Aucun diagnostic d’éligibilité valide ne couvre cette embauche. "
                                "La pièce justificative à conserver est indiquée pour chaque critère."
                            ),
                        )
                    )
                steps.append(
                    Step(
                        "Confirmer",
                        "accept",
                        [],
                        template=RECAP_TEMPLATE,
                        submit_label="Accepter l’embauche",
                        question="Vérifiez avant d’accepter l’embauche",
                    )
                )
            case "process":
                steps[-1].submit_label = "Mettre à l’étude"
        return steps

    def recap(self, forms):
        accept_form = forms["accept"]
        accept = accept_form.cleaned_data
        lines = [("Début du contrat", _fr(accept["hiring_start_at"]))]
        if accept.get("hiring_end_at"):
            lines.append(("Fin prévisionnelle", _fr(accept["hiring_end_at"])))
        if accept.get("hired_job"):
            lines.append(("Poste retenu", _label(accept_form, "hired_job", accept["hired_job"])))
        if self._iae_eligibility_needed(accept_form.data) and forms["criteria"].is_valid():
            criteria = forms["criteria"].cleaned_data
            lines.append(("Critères d’éligibilité", ", ".join(c.name for c in criteria) or "Aucun"))
        if accept.get("answer"):
            lines.append(("Message à l’usager", accept["answer"]))
        return lines

    def _meeting(self):
        """Whom to meet before answering: the job seeker, and the professional who sent the application.

        The job seeker gets an invitation through RDV-Insertion when the company uses it, the same as from the
        existing application page, and picks a slot online. Otherwise, and for the professional who sent it (a
        prescriber, or another employer), the platform has no appointment tool: an e-mail with a proposal to
        complete, and the phone number. An application the company sent itself has no one else to meet.
        """
        job_application, job_seeker, company = self.job_application, self.job_seeker, self.company
        employer = self.request.user
        jobs = ", ".join(job.display_name for job in job_application.selected_jobs.all()) or "candidature spontanée"

        def mailto(email, first_name):
            subject = f"Candidature de {job_seeker.get_full_name()}{NBSP}: proposition de rendez-vous"
            body = (
                f"Bonjour {first_name},\n\n"
                f"À la suite de la candidature de {job_seeker.get_full_name()} ({jobs}), "
                "je vous propose un rendez-vous le … à … .\n\n"
                f"Cordialement,\n{employer.get_full_name()}\n{company.display_name}"
            )
            query = urllib.parse.urlencode({"subject": subject, "body": body}, quote_via=urllib.parse.quote)
            return f"mailto:{email}?{query}"

        people = []
        if can_view_personal_information(self.request, job_seeker):
            rdvi = bool(company.rdv_solidarites_id)
            people.append(
                {
                    "role": "L’usager",
                    "name": job_seeker.get_full_name(),
                    "phone": job_seeker.phone,
                    "mailto": mailto(job_seeker.email, job_seeker.first_name) if job_seeker.email else "",
                    "rdvi_url": (
                        reverse("apply:rdv_insertion_invite", kwargs={"job_application_id": job_application.pk})
                        if rdvi
                        else ""
                    ),
                    "rdvi_pending": rdvi
                    and InvitationRequest.objects.filter(
                        company=company,
                        job_seeker=job_seeker,
                        created_at__gt=timezone.now() - settings.RDV_INSERTION_INVITE_HOLD_DURATION,
                    ).exists(),
                }
            )
        sender = job_application.sender
        role = organization = None
        if job_application.sender_kind == SenderKind.PRESCRIBER:
            role, organization = "Le prescripteur", job_application.sender_prescriber_organization
        elif job_application.sender_kind == SenderKind.EMPLOYER and job_application.sender_company_id != company.pk:
            role, organization = "L’employeur émetteur", job_application.sender_company
        if role and sender:
            people.append(
                {
                    "role": role,
                    "name": sender.get_full_name() + (f", {organization.display_name}" if organization else ""),
                    "phone": sender.phone,
                    "mailto": mailto(sender.email, sender.first_name) if sender.email else "",
                    "rdvi_url": "",
                    "rdvi_pending": False,
                }
            )
        return people

    def context(self):
        job_application = self.job_application
        return {
            "meeting": self._meeting(),
            "details_url": reverse("apply:details_for_company", kwargs={"job_application_id": job_application.pk}),
            "application_message": job_application.message,
            "resume_url": (
                reverse("apply:resume_download", kwargs={"job_application_id": job_application.pk})
                if job_application.resume_id
                else None
            ),
            "criteria_levels": CRITERIA_LEVELS,
            "criteria_filled_from_job_seeker": None,
            "company": self.company,
            "hide_value": ContractType.OTHER.value,
            # Set by the engine when the step shows them.
            "form_personal_data": None,
            "form_birth_data": None,
            "form_user_address": None,
        }

    def done(self, forms):
        decision = forms["decision"].cleaned_data["decision"]
        if decision == "refuse":
            return self._refuse(forms)
        if decision == "accept":
            return self._accept(forms)
        request = self.request
        job_application = self.job_application
        # Same transitions as apply.views.process_views.process and postpone.
        if decision == "postpone":
            job_application.answer = forms["answer"].cleaned_data["answer"]
            job_application.postpone(user=request.user)
            lines = ["Votre message est visible par l’usager et le prescripteur."]
        else:
            job_application.process(user=request.user)
            lines = []
        return Result(
            title="Réponse enregistrée", lines=[f"Statut{NBSP}: {job_application.get_state_display()}.", *lines]
        )

    def _refuse(self, forms):
        """Same as apply.views.batch_views.RefuseWizardView.done, for one application."""
        request = self.request
        reason_data = forms["refusal_reason"].cleaned_data
        applications = _get_and_lock_received_applications(request, [self.job_application.pk])
        if not applications:
            raise Http404
        job_application = applications[0]
        job_application.refusal_reason = reason_data["refusal_reason"]
        job_application.refusal_reason_shared_with_job_seeker = reason_data["refusal_reason_shared_with_job_seeker"]
        job_application.answer = forms["job_seeker_answer"].cleaned_data["job_seeker_answer"]
        if job_application.sender_kind == SenderKind.PRESCRIBER:
            job_application.answer_to_prescriber = forms["prescriber_answer"].cleaned_data["prescriber_answer"]
        try:
            job_application.refuse(user=request.user)
        except xwf_models.InvalidTransitionError:
            return Result(
                title="La candidature n’a pas pu être déclinée",
                lines=[f"Elle est au statut «{NBSP}{job_application.get_state_display()}{NBSP}»."],
            )
        lines = [f"Statut{NBSP}: {job_application.get_state_display()}."]
        if reason_data["refusal_reason"] == RefusalReason.NO_POSITION:
            job_descriptions, close_spontaneous_applications = _get_recruitment_to_close(
                self.company, [job_application]
            )
            for job_description in job_descriptions:
                job_description.is_active = False
                # Save each instance (instead of a bulk update) to record the change in field_history
                job_description.save(update_fields=["is_active", "updated_at"])
                lines.append(f"La fiche de poste {job_description.display_name} ne reçoit plus de candidatures.")
            if close_spontaneous_applications:
                self.company.spontaneous_applications_open_since = None
                self.company.save(update_fields=["spontaneous_applications_open_since", "updated_at"])
                lines.append("Les candidatures spontanées sont fermées.")
        return Result(title="Candidature déclinée", lines=lines)

    def _accept(self, forms):
        """Same as apply.views.common.BaseConfirmationView.confirm_acceptance, after the employer's diagnosis."""
        request = self.request
        if self._iae_eligibility_needed(forms["accept"].data):
            # Same as eligibility_views.BaseIAEEligibilityViewForEmployer.form_valid.
            EligibilityDiagnosis.create_diagnosis(
                self.job_seeker,
                author=request.user,
                author_siae=self.company,
                administrative_criteria=forms["criteria"].cleaned_data,
            )
        try:
            for name in ("personal_data", "user_address", "birth_data"):
                if name in forms:
                    forms[name].save()
            # The instance is committed by the transition, performed by django-xworkflows.
            job_application = forms["accept"].save(commit=False)
            professional = job_application.advisor or request.user
            job_application.accept(
                user=professional,
                action_kind=ActionKind.ACCEPT,
                assigned_to_unknown_advisor=job_application.advisor is None,
            )
            # Mark job seeker's infos as up-to-date
            job_application.job_seeker.last_checked_at = timezone.now()
            job_application.job_seeker.save(update_fields=["last_checked_at"])
        except xwf_models.InvalidTransitionError:
            transaction.set_rollback(True)
            return Result(title="La candidature n’a pas pu être acceptée", lines=["Action déjà effectuée."])
        lines = [f"Contrat à partir du {_fr(job_application.hiring_start_at)}."]
        if job_application.to_company.is_subject_to_iae_rules:
            if job_application.approval:
                lines.append(f"{PASS_IAE} {job_application.approval.number_with_spaces}.")
            else:
                lines.append(f"La demande de {PASS_IAE} est en cours de vérification auprès de nos équipes.")
        return Result(title="Candidature acceptée", lines=lines)


# Prescribers
# ------------------------------------------------------------------------------


class ProlongationJourney(Journey):
    title = "Traiter la demande de prolongation"

    def load(self, pk):
        request = self.request
        if not request.from_authorized_prescriber:
            raise Http404
        # Same rules as approvals_views.ProlongationRequestViewMixin, for a request still to process.
        self.prolongation_request = get_object_or_404(
            ProlongationRequest.objects.filter(
                prescriber_organization=request.current_organization, status=ProlongationRequestStatus.PENDING
            ).select_related("approval__user", "declared_by_siae"),
            pk=pk,
        )
        self.job_seeker = self.prolongation_request.approval.user

    def facts(self):
        # The dates are in the strip above: here, who asks and why.
        prolongation_request = self.prolongation_request
        facts = [("Demandée le", _fr(prolongation_request.created_at))]
        if prolongation_request.declared_by_siae:
            facts.append(("Par", prolongation_request.declared_by_siae.display_name))
        return facts + [("Motif", prolongation_request.get_reason_display())]

    def build_forms(self, data=None, initial=None):
        employee = self.prolongation_request.approval.user
        return {
            "decision": DecisionForm(
                data=data,
                initial=initial,
                choices=[("grant", "Accepter la prolongation"), ("deny", "Refuser la prolongation")],
            ),
            "reason": ProlongationRequestDenyInformationReasonForm(data=data, initial=initial, employee=employee),
            "reason_explanation": ProlongationRequestDenyInformationReasonExplanationForm(data=data, initial=initial),
            "proposed_actions": ProlongationRequestDenyInformationProposedActionsForm(data=data, initial=initial),
        }

    def _bar(self):
        prolongation_request = self.prolongation_request
        # Contracts are visible to authorized prescribers, the only ones processing prolongation requests.
        contract = self.job_seeker.contracts.order_by("-start_date", "-pk").first()
        contract_end = contract.end_date if contract and not contract.has_ended else None
        return prolongation_bar(
            prolongation_request.approval,
            prolongation_request.start_at,
            prolongation_request.end_at,
            contract_end=contract_end,
        )

    def steps(self, data):
        prolongation_request = self.prolongation_request
        bar = self._bar()
        requester = prolongation_request.declared_by_siae
        steps = [
            Step(
                "La demande",
                template=FACTS_TEMPLATE,
                question=(
                    f"{requester.display_name if requester else 'La structure'} demande de prolonger "
                    f"le {PASS_IAE} de {self.job_seeker.first_name}"
                ),
                bar=bar,
            ),
            Step(
                "Votre décision",
                "decision",
                question="Votre décision",
                layout={
                    "decision": Show(
                        "options",
                        {
                            "grant": (
                                None,
                                f"Le {PASS_IAE} est prolongé jusqu’au {_fr(prolongation_request.end_at)}.",
                            ),
                            "deny": (None, "La structure en est informée, avec votre motif."),
                        },
                    )
                },
            ),
        ]
        if data.get("decision") == "deny":
            steps += [
                Step(
                    "Motif",
                    "reason",
                    question="Pourquoi refusez-vous la prolongation ?",
                    layout={"reason": Show("options")},
                ),
                Step("Explication", "reason_explanation", question="Expliquez votre décision"),
            ]
            # Same condition as approvals_views.ProlongationRequestDenyView.
            if data.get("reason") == ProlongationRequestDenyReason.IAE:
                steps.append(
                    Step(
                        "Actions proposées",
                        "proposed_actions",
                        question="Quelles actions proposez-vous à la personne ?",
                        layout={"proposed_actions": Show("options")},
                    )
                )
            steps[-1].submit_label = "Refuser la prolongation"
        else:
            steps.append(
                Step(
                    "Confirmer",
                    "decision",
                    [],
                    template=RECAP_TEMPLATE,
                    submit_label="Accepter la prolongation",
                    bar=bar,
                    question="Vérifiez avant d’accepter la prolongation",
                )
            )
        return steps

    def steps_known(self, data):
        return bool(data.get("decision"))

    def recap(self, forms):
        prolongation_request = self.prolongation_request
        return [
            ("Prolongation", f"du {_fr(prolongation_request.start_at)} au {_fr(prolongation_request.end_at)}"),
            (f"Nouvelle fin du {PASS_IAE}", _fr(prolongation_request.end_at)),
        ]

    def context(self):
        pk = self.prolongation_request.pk
        report_file_url = None
        if self.prolongation_request.report_file_id:
            report_file_url = reverse(
                "approvals:prolongation_request_report_file", kwargs={"prolongation_request_id": pk}
            )
        return {
            "report_file_url": report_file_url,
            "details_url": reverse("approvals:prolongation_request_show", kwargs={"prolongation_request_id": pk}),
        }

    def done(self, forms):
        request = self.request
        prolongation_request = self.prolongation_request
        if forms["decision"].cleaned_data["decision"] == "grant":
            # Same as approvals_views.ProlongationRequestGrantView.
            try:
                with (
                    maybe_exclusion_violation(Prolongation, "exclude_prolongation_overlapping_dates"),
                    maybe_unique_violation(Prolongation, "approvals_prolongation_request_id_key"),
                ):
                    prolongation_request.grant(request.user)
            except (ExclusionViolationError, UniqueViolationError) as e:
                return Result(title="La prolongation n’a pas pu être acceptée", lines=[str(e)])
            return Result(
                title="Prolongation acceptée",
                lines=[f"Le {PASS_IAE} se termine désormais le {_fr(prolongation_request.end_at)}."],
            )
        # Same as approvals_views.ProlongationRequestDenyView.
        cleaned_data = forms["reason"].cleaned_data | forms["reason_explanation"].cleaned_data
        if cleaned_data["reason"] == ProlongationRequestDenyReason.IAE:
            cleaned_data |= forms["proposed_actions"].cleaned_data
        prolongation_request.deny(request.user, ProlongationRequestDenyInformation(**cleaned_data))
        return Result(title="Prolongation refusée", lines=["La structure qui l’a demandée en est informée."])


class BarriersForm(forms.Form):
    """The barriers the professional confirms, among those the report knows. Unchecked: dismissed or not stated."""

    barriers = forms.MultipleChoiceField(
        label="Freins à lever",
        choices=ProSupportReportBarrier.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, suggested=None, hints=None, **kwargs):
        super().__init__(*args, **kwargs)
        # The barriers checked at first, and where each comes from, by barrier.
        self.suggested = suggested or []
        self.hints = hints or {}

    def options(self):
        """Each barrier with its icon, whether it is checked and where it comes from, for the step's template."""
        checked = set(self["barriers"].value() or [])
        return [
            {
                "value": value,
                "label": label,
                "icon": BARRIER_ICONS[value],
                "checked": value in checked,
                "hint": self.hints.get(value, ""),
                "id": f"id_barriers_{index}",
            }
            for index, (value, label) in enumerate(self.fields["barriers"].choices)
        ]


class EligibilityJourney(Journey):
    title = "Valider l’éligibilité IAE"

    def load(self, pk):
        request = self.request
        if not request.from_authorized_prescriber:
            raise Http404
        self.job_seeker = get_object_or_404(User.objects.filter(kind=UserKind.JOB_SEEKER), public_id=pk)
        # Same rule as eligibility_views.BaseIAEEligibilityViewForPrescriber: nothing to do with a valid PASS IAE.
        if self.job_seeker.approvals.valid().exists():
            raise Http404
        self.eligibility_diagnosis = EligibilityDiagnosis.objects.last_considered_valid(self.job_seeker, None)
        self.criteria_filled_from_job_seeker = None

    def identity(self):
        # Under the name, and masked with it.
        if not can_view_personal_information(self.request, self.job_seeker):
            return ""
        profile = self.job_seeker.jobseeker_profile
        parts = []
        if profile.age is not None:
            parts.append(f"{profile.age}{NBSP}ans")
        if self.job_seeker.city:
            department = f" ({self.job_seeker.department})" if self.job_seeker.department else ""
            parts.append(f"{self.job_seeker.city}{department}")
        if profile.pole_emploi_id:
            parts.append(f"ID France Travail {profile.pole_emploi_id}")
        return " · ".join(parts)

    def _job_application(self):
        """The job application the action comes from (actions._eligibility_to_validate): the oldest pending one to
        an SIAE; else the latest."""
        job_applications = self.job_seeker.job_applications.select_related(
            "to_company", "sender", "sender_company", "sender_prescriber_organization"
        )
        pending = job_applications.filter(
            state__in=JobApplicationWorkflow.PENDING_STATES, to_company__kind__in=CompanyKind.siae_kinds()
        ).order_by("created_at")
        return pending.first() or job_applications.order_by("-created_at").first()

    def _relationship(self):
        """What links the professional, or their organization, to the person."""
        request = self.request
        assignments = (
            JobSeekerAssignment.objects.filter(
                job_seeker=self.job_seeker, prescriber_organization=request.current_organization, ended_at=None
            )
            .select_related("professional")
            .order_by("created_at")
        )
        own = next((each for each in assignments if each.professional_id == request.user.pk), None)
        assignment = own or assignments.first()
        if assignment is None:
            return "Pas encore accompagnée par votre structure"
        if own:
            text = f"Vous l’accompagnez depuis le {_fr(own.created_at)}"
        else:
            text = f"Accompagnée par {assignment.professional.get_full_name()} depuis le {_fr(assignment.created_at)}"
        # The last action, when it is not the one that started the assignment.
        if assignment.last_action_kind and _fr(assignment.last_action_at) != _fr(assignment.created_at):
            action = assignment.get_last_action_kind_display()
            text += f", dernière action le {_fr(assignment.last_action_at)}{NBSP}: {action}"
        return text

    def _iae_history(self):
        """The person's IAE path in a few words: there is no valid PASS IAE here (see load)."""
        approval = self.job_seeker.approvals.order_by("-end_at").first()
        if approval:
            return f"{PASS_IAE} expiré le {_fr(approval.end_at)}"
        diagnosis = EligibilityDiagnosis.objects.filter(job_seeker=self.job_seeker).order_by("-expires_at").first()
        if diagnosis and diagnosis != self.eligibility_diagnosis:
            return f"Diagnostic d’éligibilité précédent expiré le {_fr(diagnosis.expires_at)}"
        return f"Jamais de {PASS_IAE}"

    def summary(self):
        job_application = self._job_application()
        lines = []
        if job_application:
            title = f"Candidature du {_fr(job_application.created_at)} · {job_application.to_company.display_name}"
            job = job_application.selected_jobs.first()
            if job_application.sender_id == self.request.user.pk:
                sender = "envoyée par vous"
            elif job_application.sender:
                sender = f"envoyée par {job_application.sender.get_full_name()}"
                organization = job_application.sender_company or job_application.sender_prescriber_organization
                if organization:
                    sender += f" ({organization.display_name})"
            else:
                sender = ""
            job_name = job.display_name if job else "Candidature spontanée"
            lines.append(" · ".join(part for part in (job_name, sender) if part))
            lines.append(f"{self._relationship()} · {self._iae_history()}")
        else:
            title = self._relationship()
            lines.append(self._iae_history())
        return Summary(
            title,
            lines,
            url=reverse("next_steps_views:job_seeker", kwargs={"public_id": self.job_seeker.public_id}),
        )

    def build_forms(self, data=None, initial=None):
        # The barriers' default depends on the criteria chosen first: only computed for a display (see engine).
        displayed = initial
        if data is None and initial is None:
            # Same initial criteria as eligibility_views.BaseIAEEligibilityViewForPrescriber.
            initial = {}
            if self.eligibility_diagnosis:
                initial["administrative_criteria"] = self.eligibility_diagnosis.administrative_criteria.all()
            elif self.job_seeker.last_checked_at > timezone.now() - timezone.timedelta(hours=24):
                self.criteria_filled_from_job_seeker = get_criteria_from_job_seeker(self.job_seeker)
                initial["administrative_criteria"] = self.criteria_filled_from_job_seeker
        criteria_form = AdministrativeCriteriaForm(
            is_authorized_prescriber=True, siae=None, data=data, initial=initial
        )
        suggested, hints = self._suggested_barriers(criteria_form)
        barriers_initial = None
        if displayed is not None:
            # Not answered yet: the barriers the chosen criteria and the earlier statements suggest.
            answered = displayed.get("barriers")
            barriers_initial = {"barriers": suggested if answered is None else answered}
        return {
            "criteria": criteria_form,
            "barriers": BarriersForm(data=data, initial=barriers_initial, suggested=suggested, hints=hints),
        }

    def _statements(self):
        if not hasattr(self, "_latest_statements"):
            self._latest_statements = (
                JobSeekerBarrier.objects.filter(job_seeker=self.job_seeker)
                .select_related("author", "author_prescriber_organization", "author_company")
                .latest_by_barrier()
            )
        return self._latest_statements

    def _suggested_barriers(self, criteria_form):
        """The barriers to check at first, and where each comes from: the chosen criteria, the earlier statements.

        A barrier dismissed before stays unchecked, even if a criterion hints at it again: no need to dismiss it at
        each validation.
        """
        hints = {}
        for name, criterion in criteria_form.OBJECTS.items():
            if name in criteria_form.fields and criteria_form[name].value():
                for key in CRITERIA_BARRIERS.get(criterion.kind, []):
                    hints.setdefault(key, f"Critère{NBSP}: {criterion.name}")
        suggested = set(hints)
        for key, statement in self._statements().items():
            by = statement.author.get_full_name() if statement.author else ""
            if statement.author_organization:
                organization = statement.author_organization.display_name
                by = f"{by} ({organization})" if by else organization
            when = f"le {_fr(statement.created_at)}" + (f" par {by}" if by else "")
            if statement.status == BarrierStatus.CONFIRMED:
                suggested.add(key)
                hints[key] = f"Confirmé {when}"
            else:
                # Dismissed or lifted: left unchecked, saying so.
                suggested.discard(key)
                hints[key] = f"{'Levé' if statement.status == BarrierStatus.LIFTED else 'Écarté'} {when}"
        return sorted(suggested, key=list(ProSupportReportBarrier.values).index), hints

    def steps(self, data):
        expires_at = EligibilityDiagnosis._expiration_date(AuthorKind.PRESCRIBER)
        return [
            Step(
                "Les critères",
                "criteria",
                template="next_steps/journeys/criteria.html",
                question="Quels critères administratifs avez-vous constatés ?",
                hint=(
                    "À l’issue d’un diagnostic socio-professionnel réalisé lors d’un entretien individuel. "
                    "Il est recommandé de sélectionner les critères correspondants."
                ),
            ),
            Step(
                "Les freins",
                "barriers",
                template="next_steps/journeys/barriers.html",
                question=f"Les freins à lever pour {self.job_seeker.first_name}",
                hint=(
                    "Les critères que vous avez cochés laissent penser à ces freins. Décochez ceux qui ne "
                    "s’appliquent pas, ajoutez ceux que vous avez constatés. Ils apparaîtront dans "
                    f"«{NBSP}Freins à lever{NBSP}», visibles des professionnels qui accompagnent la personne."
                ),
            ),
            Step(
                "Confirmer",
                ("criteria", "barriers"),
                [],
                template=RECAP_TEMPLATE,
                submit_label="Valider l’éligibilité",
                question=f"Vous confirmez l’éligibilité IAE de {self.job_seeker.first_name}",
                boxes=[
                    Box(
                        "Pour un diagnostic réalisé par un prescripteur habilité.",
                        title=f"Diagnostic valable jusqu’au {_fr(expires_at)}",
                        variant="ok",
                    )
                ],
            ),
        ]

    def recap(self, forms):
        criteria = forms["criteria"].cleaned_data
        barriers = [ProSupportReportBarrier(key).label for key in forms["barriers"].cleaned_data["barriers"]]
        return [
            ("Critères administratifs", ", ".join(c.name for c in criteria) or "Aucun critère sélectionné"),
            ("Freins à lever", ", ".join(barriers) or "Aucun frein"),
        ]

    def context(self):
        return {
            "ITOU_DIAGNOSTIC_URL": ITOU_DIAGNOSTIC_URL,
            "criteria_filled_from_job_seeker": self.criteria_filled_from_job_seeker,
            "criteria_levels": CRITERIA_LEVELS,
        }

    def done(self, forms):
        request = self.request
        # Same as eligibility_views.BaseIAEEligibilityViewForPrescriber.form_valid.
        if self.eligibility_diagnosis:
            EligibilityDiagnosis.update_diagnosis(
                self.eligibility_diagnosis,
                author=request.user,
                author_prescriber_organization=request.current_organization,
                administrative_criteria=forms["criteria"].cleaned_data,
            )
        else:
            EligibilityDiagnosis.create_diagnosis(
                self.job_seeker,
                author=request.user,
                author_prescriber_organization=request.current_organization,
                administrative_criteria=forms["criteria"].cleaned_data,
            )
        diagnosis = EligibilityDiagnosis.objects.last_considered_valid(self.job_seeker, None)
        confirmed = self._save_barriers(forms["barriers"], diagnosis)
        lines = [f"Valable jusqu’au {_fr(diagnosis.expires_at)}."]
        if confirmed:
            lines.append(
                f"{len(confirmed)} frein{'s' if len(confirmed) > 1 else ''} à lever{NBSP}: "
                + ", ".join(ProSupportReportBarrier(key).label for key in confirmed)
                + "."
            )
        return Result(title="Éligibilité validée", lines=lines)

    def _save_barriers(self, barriers_form, diagnosis):
        """State each checked barrier as confirmed, each suggested one unchecked as dismissed."""
        request = self.request
        checked = barriers_form.cleaned_data["barriers"]
        dismissed = [key for key in barriers_form.suggested if key not in checked]
        # A barrier confirmed before and unchecked now is dismissed too.
        dismissed += [
            key
            for key, statement in self._statements().items()
            if statement.status == BarrierStatus.CONFIRMED and key not in checked and key not in dismissed
        ]
        JobSeekerBarrier.objects.bulk_create(
            [
                JobSeekerBarrier(
                    job_seeker=self.job_seeker,
                    barrier=key,
                    status=status,
                    eligibility_diagnosis=diagnosis,
                    author=request.user,
                    author_prescriber_organization=request.current_organization,
                )
                for keys, status in ((checked, BarrierStatus.CONFIRMED), (dismissed, BarrierStatus.DISMISSED))
                for key in keys
            ]
        )
        return checked


class ProSupportRequestForm(forms.Form):
    subject = forms.CharField(label="Objet")
    body = forms.CharField(label="Message", widget=forms.Textarea(attrs={"rows": 12}))


class ProSupportRequestJourney(Journey):
    """Only the SIAE fills the report: the prescriber asks for it by e-mail, from their own mailbox.

    Like the button of the job seeker's page, the platform neither sends nor stores anything.
    """

    title = "Demander le bilan d’accompagnement"

    def load(self, pk):
        request = self.request
        if not request.from_authorized_prescriber:
            raise Http404
        assigned = User.objects.filter(
            pk__in=User.objects.assigned_job_seeker_ids(request.user, request.current_organization, archived=False)
        )
        self.job_seeker = get_object_or_404(
            assigned.at_end_of_journey()
            .with_end_of_journey()
            .annotate(company_email=_pro_support_request_company_email()),
            public_id=pk,
        )
        # The job seeker's name is in the message: same rule as the job seeker's page.
        if not self.job_seeker.company_email or not can_view_personal_information(request, self.job_seeker):
            raise Http404

    def facts(self):
        return [("Destinataire", self.job_seeker.company_email)]

    def build_forms(self, data=None, initial=None):
        if data is None and not initial:
            situation = (
                PRO_SUPPORT_REQUEST_CONTRACT_ENDED
                if self.job_seeker.last_contract_ended_with_valid_approval
                else PRO_SUPPORT_REQUEST_CONTRACT_ENDING_SOON
            ).format(job_seeker_full_name=self.job_seeker.get_full_name())
            initial = {
                "subject": PRO_SUPPORT_REQUEST_EMAIL_SUBJECT,
                "body": PRO_SUPPORT_REQUEST_EMAIL_BODY.format(situation=situation),
            }
        return {"message": ProSupportRequestForm(data=data, initial=initial)}

    def steps(self, data):
        return [
            Step(
                "Le message",
                "message",
                submit_label="Préparer l’e-mail",
                question="Votre message à la structure d’insertion",
                hint="Il s’ouvrira dans votre messagerie, prêt à être envoyé. Vous pouvez le modifier ici avant.",
            )
        ]

    def done(self, forms):
        message = forms["message"].cleaned_data
        query = urllib.parse.urlencode(
            {"subject": message["subject"], "body": message["body"]}, quote_via=urllib.parse.quote
        )
        return Result(
            title="Votre e-mail est prêt",
            lines=[
                f"Il s’ouvre dans votre messagerie, adressé à {self.job_seeker.company_email}.",
                "La plateforme n’enregistre pas cet envoi. "
                f"Le bilan apparaîtra dans «{NBSP}À faire{NBSP}» une fois rempli par la structure.",
            ],
            link=("Ouvrir dans ma messagerie", f"mailto:{self.job_seeker.company_email}?{query}"),
        )


class OrientationJourney(Journey):
    """Orient the job seeker towards an insertion service, from a barrier's solutions, in the side drawer.

    The orientation wizard's three steps (insertion_views.OrientationWizardView), with its forms, its rules and its
    creation (create_orientation): the same e-mails and notifications. The key is "<job seeker>.<service>".
    """

    title = "Orienter vers un service"

    def load(self, pk):
        request = self.request
        if not can_orient_towards_insertion_service(request):
            raise Http404
        public_id, _, service_id = pk.partition(".")
        if not service_id.isdigit():
            raise Http404
        self.service = get_object_or_404(
            Service.objects.select_related("kind", "structure", "fee", "source").prefetch_related("publics"),
            pk=service_id,
        )
        if not self.service.is_orientable_via_internal_form:
            raise Http404
        try:
            uuid.UUID(public_id)
        except ValueError:
            raise Http404
        self.job_seeker = get_object_or_404(
            User.objects.select_related("jobseeker_profile"), kind=UserKind.JOB_SEEKER, public_id=public_id
        )

    def facts(self):
        return [("Service", self.service.name), ("Structure", self.service.structure.name)]

    def build_forms(self, data=None, initial=None):
        user = self.request.user
        # The referent is the user, unless they say otherwise: as the wizard.
        referent_initial = {
            "referent_last_name": user.last_name,
            "referent_first_name": user.first_name,
            "referent_phone": user.phone,
            "referent_email": user.email,
        } | (initial or {})
        # Files come with the last step only, the one that sends the request.
        files = self.request.FILES if data is not None else None
        return {
            "conformity": OrientationConformityForm(self.job_seeker, data=data, initial=initial),
            "referent": OrientationReferentForm(data=data, initial=referent_initial),
            "documents": OrientationDocumentsForm(data=data, files=files, initial=initial),
        }

    def steps(self, data):
        return [
            Step(
                "Les conditions",
                "conformity",
                template="next_steps/journeys/orientation_conditions.html",
                question="Les conditions d’accès au service",
                layout={"confirms_conditions": Show("options")},
            ),
            Step(
                "Le référent",
                "referent",
                question="Qui suit la demande ?",
                hint="Le service contactera cette personne. C’est vous, sauf si vous indiquez quelqu’un d’autre.",
            ),
            Step(
                "L’envoi",
                "documents",
                template="next_steps/journeys/orientation_documents.html",
                submit_label="Envoyer la demande",
                question="Les documents, puis l’envoi",
                files=True,
            ),
        ]

    def context(self):
        return {
            "service": self.service,
            "missing_fields": get_missing_orientation_beneficiary_field_labels(self.job_seeker),
            "can_edit_job_seeker": can_edit_personal_information(self.request, self.job_seeker),
            "credential_documents": self.service.generate_extra_credential_documents_info(),
            "option": Show("options"),
        }

    def done(self, forms):
        create_orientation(
            self.request,
            service=self.service,
            job_seeker=self.job_seeker,
            referent_data=forms["referent"].cleaned_data,
            documents_data=forms["documents"].cleaned_data,
        )
        return Result(
            title="Demande d’orientation envoyée",
            lines=[
                f"«{NBSP}{self.service.name}{NBSP}» la reçoit par e-mail, avec les coordonnées du référent.",
                "Le récapitulatif vous est envoyé, ainsi qu’à l’usager.",
                f"Le frein passe dans «{NBSP}En cours{NBSP}» jusqu’à la réponse du service.",
            ],
        )


JOURNEYS = {
    "orientation": OrientationJourney,
    "bilan": ProSupportReportFillJourney,
    "demande-bilan": ProSupportRequestJourney,
    "suspension": SuspensionJourney,
    "candidature": JobApplicationJourney,
    "prolongation": ProlongationJourney,
    "eligibilite": EligibilityJourney,
}
