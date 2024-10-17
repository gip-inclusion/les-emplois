from dateutil.relativedelta import relativedelta
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q, TextChoices
from django.shortcuts import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django_select2.forms import Select2Widget

from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.enums import (
    ProlongationReason,
    ProlongationRequestDenyProposedAction,
    ProlongationRequestDenyReason,
)
from itou.approvals.models import (
    Approval,
    Prolongation,
    ProlongationRequest,
    ProlongationRequestDenyInformation,
    Suspension,
)
from itou.files.forms import ItouFileField
from itou.job_applications.enums import JobApplicationState
from itou.job_applications.models import JobApplication
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.constants import MB
from itou.utils.db import or_queries
from itou.utils.urls import add_url_params
from itou.utils.validators import MaxDateValidator, MinDateValidator
from itou.utils.widgets import DuetDatePickerWidget, RadioSelectWithDisabledChoices


class ApprovalExpiry(TextChoices):
    LESS_THAN_1_MONTH = "1", "Moins d'1 mois"
    LESS_THAN_3_MONTHS = "3", "Moins de 3 mois"
    LESS_THAN_7_MONTHS = "7", "Moins de 7 mois"
    ALL = "", "Tous"


class ApprovalForm(forms.Form):
    job_seeker = forms.ChoiceField(
        required=False,
        label="Nom",
        widget=Select2Widget(
            attrs={
                "data-placeholder": "Nom du salarié",
            }
        ),
    )
    status_valid = forms.BooleanField(label="PASS IAE valide", required=False)
    status_suspended = forms.BooleanField(label="PASS IAE valide (suspendu)", required=False)
    status_future = forms.BooleanField(label="PASS IAE valide (non démarré)", required=False)
    status_expired = forms.BooleanField(label="PASS IAE expiré", required=False)

    expiry = forms.ChoiceField(
        label="Fin du parcours en IAE",
        choices=ApprovalExpiry.choices,
        widget=forms.RadioSelect,
        initial=ApprovalExpiry.ALL,
        required=False,
    )

    def __init__(self, siae_pk, data, *args, **kwargs):
        self.siae_pk = siae_pk
        super().__init__(data, *args, **kwargs)
        self.fields["job_seeker"].choices = self._get_choices_for_job_seekers()

    def get_approvals_qs_filter(self):
        return Exists(
            JobApplication.objects.filter(
                approval=OuterRef("pk"),
                to_company_id=self.siae_pk,
                state=JobApplicationState.ACCEPTED,
            )
        )

    def _get_choices_for_job_seekers(self):
        approvals_qs = Approval.objects.filter(self.get_approvals_qs_filter())
        users_qs = User.objects.filter(kind=UserKind.JOB_SEEKER, approvals__in=approvals_qs)
        return [
            (user.pk, user.get_full_name())
            for user in users_qs.order_by("first_name", "last_name")
            if user.get_full_name()
        ]

    def get_filters_counter(self):
        return len(self.data)

    def get_qs_filters(self):
        qs_filters_list = []
        data = self.cleaned_data

        if job_seeker_id := data.get("job_seeker"):
            qs_filters_list.append(Q(user_id=job_seeker_id))

        status_filters_list = []
        now = timezone.localdate()
        suspended_qs_filter = Q(suspension__start_at__lte=now, suspension__end_at__gte=now)
        if data.get("status_valid"):
            status_filters_list.append(Q(start_at__lte=now, end_at__gte=now) & ~suspended_qs_filter)
        if data.get("status_suspended"):
            status_filters_list.append(suspended_qs_filter)
        if data.get("status_future"):
            status_filters_list.append(Q(start_at__gt=now))
        if data.get("status_expired"):
            status_filters_list.append(Q(end_at__lt=now))
        qs_filters_list.append(or_queries(status_filters_list, required=False))

        if expiry := data.get("expiry", ApprovalExpiry.ALL):
            qs_filters_list.append(Q(end_at__lt=now + relativedelta(months=int(expiry)), end_at__gte=now))

        return qs_filters_list


def get_prolongation_form(**kwargs):
    form_class = CreateProlongationForm

    try:
        reason = kwargs["data"]["reason"]
    except (KeyError, TypeError):  # "data" can be given but with a None value
        pass
    else:
        if reason and reason not in ProlongationRequest.REASONS_NOT_NEED_PRESCRIBER_OPINION:
            form_class = CreateProlongationRequestForm

    return form_class(**kwargs)


class CreateProlongationForm(forms.ModelForm):
    """Declare a prolongation. Used when the reason doesn't need to be validated by a prescriber."""

    reason = forms.ChoiceField(
        label="Motif",
        choices=ProlongationReason.choices,
        initial=None,  # Uncheck radio buttons.
        widget=RadioSelectWithDisabledChoices,
    )
    end_at = forms.DateField(widget=DuetDatePickerWidget())

    class Meta:
        model = Prolongation
        fields = [
            "reason",
            "end_at",
        ]

    def __init__(self, *args, approval, siae, back_url, **kwargs):
        super().__init__(*args, **kwargs)
        self.back_url = back_url

        # Used to display an explanation if the max duration is not possible
        self.max_end_limit = None

        if not self.instance.pk:
            # `approval` must be set before model validation to avoid violating a not-null constraint.
            self.instance.approval = approval
            self.instance.declared_by_siae = siae
            # `start_at` should begin just after the approval. It cannot be set by the user.
            self.instance.start_at = self.instance.approval.end_at
            self.instance.end_at = None

        # Customize "reason" field
        self.fields["reason"].choices = ProlongationReason.for_company(self.instance.declared_by_siae)
        other_prolongation_duration = Prolongation.objects.get_cumulative_duration_for(approval.pk)
        disabled_values = set()
        for reason, _reason_label in self.fields["reason"].choices:
            if (
                max_cumulative_duration := Prolongation.PROLONGATION_RULES[reason]["max_cumulative_duration"]
            ) is not None:
                if max_cumulative_duration <= other_prolongation_duration:
                    disabled_values.add(reason)

        if disabled_values:
            # Make those options appear as disabled
            self.fields["reason"].widget.disabled_values = disabled_values
            # Prevent those options to be accepted
            self.fields["reason"]._choices = [
                (value, label) for value, label in self.fields["reason"]._choices if value not in disabled_values
            ]
        self.fields["reason"].widget.attrs.update(
            {
                "hx-trigger": "change",
                "hx-post": add_url_params(
                    reverse(
                        "approvals:prolongation_form_for_reason",
                        kwargs={"approval_id": self.instance.approval_id},
                    ),
                    {"back_url": self.back_url},
                ),
                "hx-params": "not end_at",  # Clear "end_at" when switching reason
                "hx-swap": "outerHTML",
                "hx-target": "#mainForm",
            }
        )

        # Customize "end_at" field
        end_at = self.fields["end_at"]
        end_at.label = f"Du {self.instance.start_at:%d/%m/%Y} au"
        reason_not_validated = self.data.get("reason")
        try:
            rule_details = Prolongation.PROLONGATION_RULES[reason_not_validated]
        except KeyError:
            end_at.disabled = True
        else:
            end_at.help_text = rule_details["help_text"]
            max_duration_end_at = self.instance.start_at + rule_details["max_duration"]
            max_cumulative_duration_end_at = Prolongation.get_max_end_at(
                self.instance.approval_id, self.instance.start_at, reason_not_validated
            )
            max_end_at = min(max_duration_end_at, max_cumulative_duration_end_at)
            if max_cumulative_duration_end_at < max_duration_end_at:
                self.max_end_limit = {
                    "max_date": max_end_at,
                    "max_duration": (
                        f"{rule_details['max_duration_label']} ({rule_details['max_duration'].days} jours)"
                    ),
                }
            end_at.widget.attrs["max"] = max_end_at
            if reason_not_validated == ProlongationReason.SENIOR_CDI and not self.data.get("end_at"):
                # The field should have an initial value, but Django ignores `initial` when the form is bound.
                # Due to the POSTing of the form via HTMX, the form is always bound and `initial` is never read.
                # Instead, force the default value when switching to ProlongationReason.SENIOR_CDI.
                self.data = self.data.copy()
                self.data["end_at"] = max_end_at
            end_at.widget.attrs["min"] = self.instance.start_at
            end_at.validators.append(MinDateValidator(self.instance.start_at))
            # Try switching reason with a date beyond the max_end_at of the new reason
            end_at.validators.append(MaxDateValidator(max_end_at))


class CreateProlongationRequestForm(CreateProlongationForm):
    """Request a prolongation. Used when the reason need to be validated by a prescriber."""

    email = forms.EmailField(
        label="Adresse e-mail du prescripteur habilité sollicité pour cette prolongation",
        help_text=(
            "Attention : l'adresse e-mail doit correspondre à un compte utilisateur de type prescripteur habilité"
        ),
        required=False,
        error_messages={
            "required": "Vous devez choisir un prescripteur habilité",
        },
    )
    prescriber_organization = forms.ModelChoiceField(
        queryset=PrescriberOrganization.objects.none(),
        label="",
        empty_label="Sélectionnez l'organisation du prescripteur habilité",
        required=False,
        disabled=True,
    )

    require_phone_interview = forms.BooleanField(
        label="Demande d'entretien téléphonique pour apporter des explications supplémentaires",
        required=False,
    )
    contact_email = forms.EmailField(
        label="Votre e-mail",
        widget=forms.EmailInput(attrs={"placeholder": "employeur@email.fr"}),
        required=False,
        disabled=True,
        error_messages={
            "required": "Veuillez saisir une adresse e-mail de contact",
        },
    )
    contact_phone = forms.CharField(
        label="Votre numéro de téléphone",
        widget=forms.TextInput(attrs={"placeholder": "Merci de privilégier votre ligne directe"}),
        required=False,
        disabled=True,
        error_messages={
            "required": "Veuillez saisir un numéro de téléphone de contact",
        },
    )

    class Meta(CreateProlongationForm.Meta):
        model = ProlongationRequest
        fields = CreateProlongationForm.Meta.fields + [
            "email",
            "prescriber_organization",
            "require_phone_interview",
            "contact_email",
            "contact_phone",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Customize "report_file" field
        unvalidated_reason = self.data.get("reason")
        if (
            unvalidated_reason in PROLONGATION_REPORT_FILE_REASONS
            and self.instance.declared_by_siae.can_upload_prolongation_report
        ):
            report_file_field = ItouFileField(
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                max_upload_size=MB,
                label="Fichier bilan du candidat",
            )
            self.fields["report_file"] = report_file_field

        # Customize "email" and "prescriber_organization" fields
        if unvalidated_reason not in Prolongation.REASONS_NOT_NEED_PRESCRIBER_OPINION:
            self.fields["email"].required = True
        self.fields["email"].widget.attrs.update({"placeholder": "Adresse e-mail du prescripteur habilité"})
        self.fields["prescriber_organization"].widget.attrs.update(
            {
                "hx-trigger": "change",
                "hx-post": reverse(
                    "approvals:check_prescriber_email", kwargs={"approval_id": self.instance.approval_id}
                ),
                "hx-target": "#check_prescriber_email",
                "hx-select": "#check_prescriber_email",
            }
        )

        if kwargs.get("data"):
            if email := kwargs["data"].get("email"):
                orgs = PrescriberOrganization.objects.filter(
                    members__email=email,
                    members__is_active=True,
                    prescribermembership__is_active=True,
                    is_authorized=True,
                )
                self.fields["prescriber_organization"].queryset = orgs
                self.fields["prescriber_organization"].disabled = False
                self.fields["prescriber_organization"].required = True
                if len(orgs) == 1:
                    # UI choice : display the select box with a unique selected choice
                    # IMO a simple label would have done the job
                    self.fields["prescriber_organization"].empty_label = None

        # Customize "require_phone_interview", "contact_email" and "contact_phone" fields
        self.fields["require_phone_interview"].widget.attrs.update(
            {
                "hx-trigger": "change",
                "hx-post": reverse(
                    "approvals:check_contact_details", kwargs={"approval_id": self.instance.approval_id}
                ),
                "hx-target": "#check_contact_details",
                "hx-select": "#check_contact_details",
            }
        )
        if forms.BooleanField().to_python(self.data.get("require_phone_interview", False)):
            self.fields["contact_email"].disabled = self.fields["contact_phone"].disabled = False
            self.fields["contact_email"].required = self.fields["contact_phone"].required = True

    def clean(self):
        super().clean()

        if email := self.cleaned_data.get("email"):
            validated_by = User.objects.filter(email=email).first()
            if validated_by and validated_by.is_prescriber_with_authorized_org:
                self.instance.validated_by = validated_by
            else:
                # Either does not exist or is not an authorized prescriber
                self.add_error(
                    "email",
                    format_html(
                        "Cet utilisateur n’est pas inscrit en tant que prescripteur habilité sur les "
                        'emplois de l’inclusion, vous pouvez <a href="{}" rel="noopener" target="_blank" '
                        'aria-label="Rechercher des prescripteurs (ouverture dans une nouvelle fenêtre)">retrouver ici'
                        "</a> des prescripteurs habilités autour de chez vous.",
                        reverse("search:prescribers_home"),
                    ),
                )


class ProlongationRequestFilterForm(forms.Form):
    only_pending = forms.BooleanField(
        label="Voir uniquement les demandes à traiter",
        label_suffix="",
        required=False,
    )


class ProlongationRequestDenyInformationReasonForm(forms.ModelForm):
    reason = forms.ChoiceField(
        choices=ProlongationRequestDenyReason.choices,
        initial=None,  # Uncheck radio buttons.
        widget=forms.RadioSelect(),
    )

    class Meta:
        model = ProlongationRequestDenyInformation
        fields = ["reason"]

    def __init__(self, *args, employee, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields[
            "reason"
        ].label = f"Pour quel motif refusez-vous la prolongation du parcours IAE de {employee.get_full_name()} ?"


class ProlongationRequestDenyInformationReasonExplanationForm(forms.ModelForm):
    class Meta:
        model = ProlongationRequestDenyInformation
        fields = ["reason_explanation"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["reason_explanation"].widget.attrs["placeholder"] = "Message"


class ProlongationRequestDenyInformationProposedActionsForm(forms.ModelForm):
    proposed_actions = forms.MultipleChoiceField(
        label="Quelle(s) action(s) envisagez-vous de proposer au candidat ?",
        choices=ProlongationRequestDenyProposedAction.choices,
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = ProlongationRequestDenyInformation
        fields = ["proposed_actions", "proposed_actions_explanation"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["proposed_actions_explanation"].label = "Précisions"
        self.fields["proposed_actions_explanation"].required = True
        self.fields["proposed_actions_explanation"].widget.attrs["placeholder"] = "Message"


class SuspensionForm(forms.ModelForm):
    """
    Create or edit a suspension.

    Suspension.clean() will handle the validation.
    """

    set_default_end_date = forms.BooleanField(
        required=False,
        label="Je ne connais pas la date de fin de la suspension.",
        help_text=f"La Plateforme indiquera {Suspension.MAX_DURATION_MONTHS} mois par défaut.",
    )

    class Meta:
        model = Suspension
        fields = [
            # Order is important for the template.
            "start_at",
            "end_at",
            "set_default_end_date",
            "reason",
            "reason_explanation",
        ]
        widgets = {
            "reason": forms.RadioSelect(),
            "start_at": DuetDatePickerWidget(),
            "end_at": DuetDatePickerWidget(),
        }
        help_texts = {
            "start_at": mark_safe(
                "Au format JJ/MM/AAAA, par exemple 20/12/1978."
                "<br>"
                "La suspension ne doit pas chevaucher une suspension déjà existante."
                " Elle ne peut pas commencer dans le futur."
            ),
            "end_at": mark_safe(
                "Au format JJ/MM/AAAA, par exemple 20/12/1978."
                "<br>"
                f"Renseignez une date de fin à {Suspension.MAX_DURATION_MONTHS} mois "
                "si le contrat de travail est terminé ou rompu."
            ),
        }

    def __init__(self, *args, **kwargs):
        self.approval = kwargs.pop("approval")
        self.siae = kwargs.pop("siae")
        super().__init__(*args, **kwargs)
        # Show new reasons but keep old ones for history.
        self.fields["reason"].choices = Suspension.Reason.displayed_choices_for_siae(self.siae)

        # End date is not strictly required because it can be set
        # with `set_default_end_date` input
        self.fields["end_at"].required = False

        today = timezone.localdate()
        if self.instance.pk:
            referent_date = self.instance.created_at.date()
            suspension_pk = self.instance.pk
        else:
            referent_date = today
            suspension_pk = None
            self.instance.siae = self.siae
            self.instance.approval = self.approval
            self.fields["reason"].initial = None  # Uncheck radio buttons.

        min_start_at = Suspension.next_min_start_at(self.approval, suspension_pk, referent_date, True)
        # A suspension is backdatable but cannot start in the future.
        self.fields["start_at"].widget = DuetDatePickerWidget({"min": min_start_at, "max": today})
        self.fields["end_at"].widget = DuetDatePickerWidget(
            {"min": min_start_at, "max": Suspension.get_max_end_at(today)}
        )

    def clean_start_at(self):
        start_at = self.cleaned_data.get("start_at")

        # The start of a suspension must follow retroactivity rule
        suspension_pk = None
        referent_date = None
        if self.instance.pk:
            suspension_pk = self.instance.pk
            referent_date = self.instance.created_at.date()

        next_min_start_at = Suspension.next_min_start_at(self.approval, suspension_pk, referent_date, True)
        if start_at < next_min_start_at:
            raise ValidationError(
                f"Vous ne pouvez pas saisir une date de début de suspension "
                f"qui précède le {next_min_start_at:%d/%m/%Y}."
            )

        return start_at

    def clean(self):
        super().clean()

        set_default_end_date = self.cleaned_data.get("set_default_end_date")
        start_at = self.cleaned_data.get("start_at")

        # If the end date of the suspension is not known,
        # it is set to `start_date` + 36 months.
        # If `set_default_end_date` is not checked, `end_at` field is required.
        # See Suspension model clean/validation.
        if set_default_end_date and start_at:
            self.cleaned_data["end_at"] = Suspension.get_max_end_at(start_at)


class SuspensionEndDateForm(forms.Form):
    """
    first_day_back_to_work is the day after the last day of the suspension (end_at).
    """

    first_day_back_to_work = forms.DateField(
        widget=DuetDatePickerWidget(),
        label="A quelle date le salarié va-t-il réintégrer votre entreprise ?",
        help_text=(
            "La date de fin de suspension sera mise à jour, le PASS sera de nouveau actif "
            "à la date de réintégration du candidat."
        ),
    )

    def __init__(self, *args, approval, instance, siae, **kwargs):
        self.approval = approval
        self.siae = siae
        self.instance = instance
        super().__init__(*args, **kwargs)

        self.minimal_first_day_back_to_work = self.instance.start_at + relativedelta(days=1)
        self.initial["first_day_back_to_work"] = max(self.minimal_first_day_back_to_work, timezone.localdate())
        self.fields["first_day_back_to_work"].widget = DuetDatePickerWidget(
            {"min": self.minimal_first_day_back_to_work, "max": self.instance.end_at}
        )

    def clean_first_day_back_to_work(self):
        first_day_back_to_work = self.cleaned_data.get("first_day_back_to_work")

        if first_day_back_to_work <= self.instance.start_at:
            raise ValidationError(
                "Vous ne pouvez pas saisir une date de réintégration antérieure au début de la suspension."
            )
        if first_day_back_to_work >= self.instance.end_at:
            raise ValidationError(
                "Vous ne pouvez pas saisir une date de réintégration postérieure à la fin de la suspension."
            )
        return first_day_back_to_work
