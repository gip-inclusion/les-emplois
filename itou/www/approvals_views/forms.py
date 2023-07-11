from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django_select2.forms import Select2MultipleWidget

from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.enums import ProlongationReason
from itou.approvals.models import Approval, Prolongation, ProlongationRequest, Suspension
from itou.job_applications.models import JobApplication, JobApplicationWorkflow
from itou.prescribers.models import PrescriberOrganization
from itou.users.enums import UserKind
from itou.users.models import User
from itou.utils.widgets import DuetDatePickerWidget


class ApprovalForm(forms.Form):
    users = forms.MultipleChoiceField(required=False, label="Nom", widget=Select2MultipleWidget)
    status_valid = forms.BooleanField(label="PASS IAE valide", required=False)
    status_suspended = forms.BooleanField(label="PASS IAE valide (suspendu)", required=False)
    status_future = forms.BooleanField(label="PASS IAE valide (non démarré)", required=False)
    status_expired = forms.BooleanField(label="PASS IAE expiré", required=False)

    def __init__(self, siae_pk, *args, **kwargs):
        self.siae_pk = siae_pk
        super().__init__(*args, **kwargs)
        self.fields["users"].choices = self._get_choices_for_job_seekers()

    def _get_approvals_qs_filter(self):
        return Exists(
            JobApplication.objects.filter(
                approval=OuterRef("pk"),
                to_siae_id=self.siae_pk,
                state=JobApplicationWorkflow.STATE_ACCEPTED,
            )
        )

    def _get_choices_for_job_seekers(self):
        approvals_qs = Approval.objects.filter(self._get_approvals_qs_filter())
        users_qs = User.objects.filter(kind=UserKind.JOB_SEEKER, approvals__in=approvals_qs)
        return [
            (user.pk, user.get_full_name().title())
            for user in users_qs.order_by("first_name", "last_name")
            if user.get_full_name()
        ]

    def get_filters_counter(self):
        return len(self.data)

    def get_qs_filters(self):
        qs_filters_list = [self._get_approvals_qs_filter()]
        data = self.cleaned_data

        if users := data.get("users"):
            qs_filters_list.append(Q(user_id__in=users))

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
        if status_filters_list:
            status_filters = Q()
            for status_filter in status_filters_list:
                status_filters |= status_filter
            qs_filters_list.append(status_filters)

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
        choices=ProlongationReason.choices,
        initial=None,  # Uncheck radio buttons.
        widget=forms.RadioSelect(),
    )
    end_at = forms.DateField(
        required=False,  # Checked by model clean(), avoid double validation message
        initial=None,
        widget=DuetDatePickerWidget(),
    )

    class Meta:
        model = Prolongation
        fields = [
            "reason",
            "end_at",
        ]

    def __init__(self, *args, approval, siae, **kwargs):
        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            # `approval` must be set before model validation to avoid violating a not-null constraint.
            self.instance.approval = approval
            self.instance.declared_by_siae = siae
            # `start_at` should begin just after the approval. It cannot be set by the user.
            self.instance.start_at = self.instance.approval.end_at
            self.instance.end_at = None

        # Customize "reason" field
        self.fields["reason"].choices = ProlongationReason.for_siae(self.instance.declared_by_siae)
        self.fields["reason"].widget.attrs.update(
            {
                "hx-post": reverse("approvals:toggle_upload_panel", kwargs={"approval_id": self.instance.approval_id}),
                "hx-target": "#upload_panel",
                "hx-select": "#upload_panel",
            }
        )

        # Customize "end_at" field
        self.fields["end_at"].widget.attrs.update(
            {
                "min": self.instance.start_at,
                "max": Prolongation.get_max_end_at(self.instance.start_at),
            }
        )
        self.fields["end_at"].label = f'Du {self.instance.start_at.strftime("%d/%m/%Y")} au'

        end_at_extra_help_text = ""
        if self.data and self.data.get("reason"):
            prolongation_duration = Prolongation.MAX_CUMULATIVE_DURATION[self.data.get("reason")]["label"]
            end_at_extra_help_text = (
                f" <strong>(Durée maximum de 1 an renouvelable jusqu'à {prolongation_duration})</strong>."
            )
        self.fields["end_at"].help_text = mark_safe(
            f"Date jusqu'à laquelle le PASS IAE doit être prolongé{end_at_extra_help_text}<br>"
            f"Au format JJ/MM/AAAA, par exemple 20/12/1978."
        )


class CreateProlongationRequestForm(CreateProlongationForm):
    """Request a prolongation. Used when the reason need to be validated by a prescriber."""

    report_file_path = forms.CharField(required=False, disabled=True, widget=forms.HiddenInput())
    uploaded_file_name = forms.CharField(required=False, disabled=True, widget=forms.HiddenInput())
    email = forms.EmailField(
        label="E-mail du prescripteur habilité sollicité pour cette prolongation",
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Customize "report_file_path" and "uploaded_file_name" field
        if (
            self.data.get("reason") in PROLONGATION_REPORT_FILE_REASONS
            and self.instance.declared_by_siae.can_upload_prolongation_report
        ):
            self.fields["report_file_path"].required = self.fields["uploaded_file_name"].required = True
            self.fields["report_file_path"].disabled = self.fields["uploaded_file_name"].disabled = False

        # Customize "email" and "prescriber_organization" fields
        if self.data.get("reason") not in Prolongation.REASONS_NOT_NEED_PRESCRIBER_OPINION:
            self.fields["email"].required = True
        self.fields["email"].widget.attrs.update({"placeholder": "E-mail du prescripteur habilité"})
        self.fields["prescriber_organization"].widget.attrs.update(
            {
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
                "hx-post": reverse(
                    "approvals:check_contact_details", kwargs={"approval_id": self.instance.approval_id}
                ),
                "hx-target": "#check_contact_details",
                "hx-select": "#check_contact_details",
            }
        )
        if self.data.get("require_phone_interview", False) in ("True", "true", "1", "on"):  # FIXME: Better way?
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
                    "Ce prescripteur n'a pas de compte sur les emplois de l'inclusion. "
                    "Merci de renseigner l'e-mail d'un conseiller inscrit sur le service.",
                )

        # Prolongation report :
        # - is only mandatory for these reasons
        # - is temporarily limited to AI kind
        if (
            self.cleaned_data.get("reason") in PROLONGATION_REPORT_FILE_REASONS
            and self.instance.declared_by_siae.can_upload_prolongation_report
        ):
            if not self.cleaned_data.get("report_file_path") or not self.cleaned_data.get("uploaded_file_name"):
                # No visible field for this form field
                raise ValidationError("Vous devez fournir un fichier de bilan renseigné")

    class Meta(CreateProlongationForm.Meta):
        model = ProlongationRequest
        fields = CreateProlongationForm.Meta.fields + [
            "report_file_path",
            "uploaded_file_name",
            "email",
            "prescriber_organization",
            "require_phone_interview",
            "contact_email",
            "contact_phone",
        ]


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
            "reason_explanation": "Obligatoire seulement en cas de force majeure.",
        }

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
                f"qui précède le {next_min_start_at.strftime('%d/%m/%Y')}."
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


class PoleEmploiApprovalSearchForm(forms.Form):
    number = forms.CharField(
        label="Numéro",
        required=True,
        min_length=12,
        max_length=12,
        strip=True,
        help_text=("Le numéro d'agrément est composé de 12 chiffres (ex. 123456789012)."),
    )

    def clean_number(self):
        number = self.cleaned_data.get("number", "").replace(" ", "")
        if len(number) != 12:
            raise ValidationError(
                "Merci d'indiquer les 12 premiers caractères du numéro d'agrément. "
                "Exemple : 123456789012 si le numéro d'origine est 123456789012P01."
            )

        return number
