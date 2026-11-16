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

from django import forms
from django.db.models import Exists, OuterRef
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone

from itou.approvals.enums import ProlongationRequestDenyReason, ProlongationRequestStatus
from itou.approvals.models import (
    Approval,
    Prolongation,
    ProlongationRequest,
    ProlongationRequestDenyInformation,
)
from itou.companies.models import ProSupportReport
from itou.eligibility.models.iae import EligibilityDiagnosis, get_criteria_from_job_seeker
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.users.enums import ActionKind, UserKind
from itou.users.models import JobSeekerAssignment, User
from itou.users.perms import can_fill_pro_support_report
from itou.utils.constants import ITOU_DIAGNOSTIC_URL
from itou.utils.db import (
    ExclusionViolationError,
    UniqueViolationError,
    maybe_exclusion_violation,
    maybe_unique_violation,
)
from itou.utils.perms.utils import can_view_personal_information
from itou.www.apply.forms import AnswerForm
from itou.www.approvals_views.forms import (
    ProlongationRequestDenyInformationProposedActionsForm,
    ProlongationRequestDenyInformationReasonExplanationForm,
    ProlongationRequestDenyInformationReasonForm,
    SuspensionForm,
)
from itou.www.eligibility_views.forms import AdministrativeCriteriaForm
from itou.www.job_seekers_views.forms import ProSupportReportForm
from itou.www.job_seekers_views.views import (
    PRO_SUPPORT_REQUEST_CONTRACT_ENDED,
    PRO_SUPPORT_REQUEST_CONTRACT_ENDING_SOON,
    PRO_SUPPORT_REQUEST_EMAIL_BODY,
    PRO_SUPPORT_REQUEST_EMAIL_SUBJECT,
    _pro_support_request_company_email,
)


logger = logging.getLogger(__name__)

NBSP = " "
PASS_IAE = f"PASS{NBSP}IAE"
FIELDS_TEMPLATE = "next_steps/journeys/fields.html"
FACTS_TEMPLATE = "next_steps/journeys/facts.html"
RECAP_TEMPLATE = "next_steps/journeys/recap.html"


def _fr(date):
    if hasattr(date, "hour"):
        date = timezone.localdate(date)
    return f"{date:%d/%m/%Y}"


@dataclasses.dataclass
class Step:
    label: str
    # The form this step shows, by key in Journey.build_forms(), and which of its fields (None: all of them).
    form: str | None = None
    fields: list | None = None
    template: str = FIELDS_TEMPLATE
    submit_label: str = "Continuer"
    # A step that hands over to an existing screen instead of submitting: (label, url).
    handover: tuple | None = None


@dataclasses.dataclass
class Result:
    title: str
    lines: list
    # An optional main link: (label, url).
    link: tuple | None = None


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

    def build_forms(self, data=None, initial=None):
        """Forms by key: bound to data to validate, or unbound with initial values to display."""
        return {}

    def steps(self, data):
        raise NotImplementedError

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
    return dict(form.fields[field_name].choices)[value]


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

    def steps(self, data):
        if data.get("has_solution") == "False":
            follow_up = Step("Orientation", "report", ["orientation"])
        else:
            follow_up = Step("Solution", "report", ["solution"])
        return [
            Step("Freins", "report", ["barriers", "other_barrier"]),
            Step("Autonomie", "report", ["autonomy"]),
            Step("La suite", "report", ["has_solution"]),
            follow_up,
            Step("Envoi", "report", [], template=RECAP_TEMPLATE, submit_label="Envoyer le bilan"),
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
        return [
            Step("La suspension", "suspension"),
            Step("Vérifier", "suspension", [], template=RECAP_TEMPLATE, submit_label="Suspendre"),
        ]

    def recap(self, forms):
        form = forms["suspension"]
        suspension = form.cleaned_data
        lines = [
            ("Du", _fr(suspension["start_at"])),
            ("Au", _fr(suspension["end_at"])),
            ("Motif", _label(form, "reason", suspension["reason"])),
        ]
        if suspension.get("reason_explanation"):
            lines.append(("Explications", suspension["reason_explanation"]))
        return lines

    def done(self, forms):
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
        )


class JobApplicationJourney(Journey):
    title = "Répondre à la candidature"

    def load(self, pk):
        request = self.request
        if not request.from_employer:
            raise Http404
        self.job_application = get_object_or_404(
            JobApplication.objects.is_active_company_member(request.user)
            .filter(to_company=request.current_organization)
            .select_related("job_seeker", "to_company", "sender_prescriber_organization", "sender_company"),
            pk=pk,
        )
        self.job_seeker = self.job_application.job_seeker

    def facts(self):
        job_application = self.job_application
        facts = [("Reçue le", _fr(job_application.created_at)), ("Statut", job_application.get_state_display())]
        sender = job_application.sender_prescriber_organization or job_application.sender_company
        if sender:
            facts.append(("Envoyée par", sender.display_name))
        return facts

    def _choices(self):
        job_application = self.job_application
        choices = []
        if job_application.process.is_available():
            choices.append(("process", "La mettre à l’étude"))
        if job_application.postpone.is_available():
            choices.append(("postpone", "La mettre en attente, avec un message"))
        if job_application.accept.is_available():
            choices.append(("accept", "Accepter l’embauche"))
        if job_application.refuse.is_available():
            choices.append(("refuse", "Décliner la candidature"))
        return choices

    def build_forms(self, data=None, initial=None):
        return {
            "decision": DecisionForm(data=data, initial=initial, choices=self._choices()),
            "answer": AnswerForm(data=data, initial=initial),
        }

    def steps(self, data):
        pk = self.job_application.pk
        steps = [Step("La candidature", template=FACTS_TEMPLATE), Step("Votre réponse", "decision")]
        match data.get("decision"):
            case "postpone":
                steps.append(Step("Message", "answer", submit_label="Mettre en attente"))
            case "accept":
                url = reverse("apply:start-accept", kwargs={"job_application_id": pk})
                steps.append(Step("Embauche", handover=("Commencer l’embauche", url)))
            case "refuse":
                url = reverse("apply:refuse", kwargs={"job_application_id": pk})
                steps.append(Step("Refus", handover=("Décliner la candidature", url)))
            case _:
                steps[-1].submit_label = "Valider"
        return steps

    def context(self):
        return {
            "details_url": reverse("apply:details_for_company", kwargs={"job_application_id": self.job_application.pk})
        }

    def done(self, forms):
        request = self.request
        job_application = self.job_application
        # Same transitions as apply.views.process_views.process and postpone.
        if forms["decision"].cleaned_data["decision"] == "postpone":
            job_application.answer = forms["answer"].cleaned_data["answer"]
            job_application.postpone(user=request.user)
            lines = ["Votre message est visible par l’usager et le prescripteur."]
        else:
            job_application.process(user=request.user)
            lines = []
        return Result(
            title="Réponse enregistrée", lines=[f"Statut{NBSP}: {job_application.get_state_display()}.", *lines]
        )


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
        prolongation_request = self.prolongation_request
        facts = [("Demandée le", _fr(prolongation_request.created_at))]
        if prolongation_request.declared_by_siae:
            facts.append(("Par", prolongation_request.declared_by_siae.display_name))
        return facts + [
            ("Motif", prolongation_request.get_reason_display()),
            (
                "Prolongation demandée",
                f"du {_fr(prolongation_request.start_at)} au {_fr(prolongation_request.end_at)}",
            ),
            (f"Fin actuelle du {PASS_IAE}", _fr(prolongation_request.approval.end_at)),
        ]

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

    def steps(self, data):
        steps = [Step("La demande", template=FACTS_TEMPLATE), Step("Votre décision", "decision")]
        if data.get("decision") == "deny":
            steps += [Step("Motif", "reason"), Step("Explication", "reason_explanation")]
            # Same condition as approvals_views.ProlongationRequestDenyView.
            if data.get("reason") == ProlongationRequestDenyReason.IAE:
                steps.append(Step("Actions proposées", "proposed_actions"))
            steps[-1].submit_label = "Refuser la prolongation"
        else:
            steps.append(
                Step("Confirmer", "decision", [], template=RECAP_TEMPLATE, submit_label="Accepter la prolongation")
            )
        return steps

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

    def facts(self):
        job_application = self.job_seeker.job_applications.select_related("to_company").order_by("-created_at").first()
        if job_application is None:
            return []
        return [("Candidature du", _fr(job_application.created_at)), ("Chez", job_application.to_company.display_name)]

    def build_forms(self, data=None, initial=None):
        if data is None and initial is None:
            # Same initial criteria as eligibility_views.BaseIAEEligibilityViewForPrescriber.
            initial = {}
            if self.eligibility_diagnosis:
                initial["administrative_criteria"] = self.eligibility_diagnosis.administrative_criteria.all()
            elif self.job_seeker.last_checked_at > timezone.now() - timezone.timedelta(hours=24):
                self.criteria_filled_from_job_seeker = get_criteria_from_job_seeker(self.job_seeker)
                initial["administrative_criteria"] = self.criteria_filled_from_job_seeker
        return {
            "criteria": AdministrativeCriteriaForm(
                is_authorized_prescriber=True, siae=None, data=data, initial=initial
            )
        }

    def steps(self, data):
        return [
            Step("Les critères", "criteria", template="next_steps/journeys/eligibility_criteria.html"),
            Step("Confirmer", "criteria", [], template=RECAP_TEMPLATE, submit_label="Valider l’éligibilité"),
        ]

    def recap(self, forms):
        criteria = forms["criteria"].cleaned_data
        return [("Critères administratifs", ", ".join(c.name for c in criteria) or "Aucun critère sélectionné")]

    def context(self):
        return {
            "ITOU_DIAGNOSTIC_URL": ITOU_DIAGNOSTIC_URL,
            "criteria_filled_from_job_seeker": self.criteria_filled_from_job_seeker,
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
        return Result(title="Éligibilité validée", lines=[f"Valable jusqu’au {_fr(diagnosis.expires_at)}."])


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
                "Le message", "message", template="next_steps/journeys/message.html", submit_label="Préparer l’e-mail"
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


JOURNEYS = {
    "bilan": ProSupportReportFillJourney,
    "demande-bilan": ProSupportRequestJourney,
    "suspension": SuspensionJourney,
    "candidature": JobApplicationJourney,
    "prolongation": ProlongationJourney,
    "eligibilite": EligibilityJourney,
}
