from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Exists, OuterRef, Q
from django.shortcuts import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django_select2.forms import Select2MultipleWidget

from itou.approvals.constants import PROLONGATION_REPORT_FILE_REASONS
from itou.approvals.enums import ProlongationReason
from itou.approvals.models import Approval, Prolongation, Suspension
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


class DeclareProlongationForm(forms.ModelForm):
    """
    Request a prolongation.

    Prolongation.clean() will handle the validation.
    """

    report_file_path = forms.CharField(required=False, widget=forms.HiddenInput())
    uploaded_file_name = forms.CharField(required=False, widget=forms.HiddenInput())
    email = forms.EmailField(
        required=False,
        label="E-mail du prescripteur habilité sollicité pour cette prolongation",
        help_text=(
            "Attention : l'adresse e-mail doit correspondre à un compte utilisateur de type prescripteur habilité"
        ),
    )

    def __init__(self, *args, **kwargs):
        self.approval = kwargs.pop("approval")
        self.siae = kwargs.pop("siae")
        self.validated_by = None
        self.reasons_not_need_prescriber_opinion = Prolongation.REASONS_NOT_NEED_PRESCRIBER_OPINION

        super().__init__(*args, **kwargs)

        if not self.instance.pk:
            self.instance.declared_by_siae = self.siae
            # `start_at` should begin just after the approval. It cannot be set by the user.
            self.instance.start_at = Prolongation.get_start_at(self.approval)
            self.instance.end_at = None
            # `approval` must be set before model validation to avoid violating a not-null constraint.
            self.instance.approval = self.approval
            self.fields["reason"].initial = None  # Uncheck radio buttons.

        self.fields["reason"].choices = ProlongationReason.for_siae(self.siae)
        self.fields["reason"].widget.attrs.update(
            {
                "hx-post": reverse("approvals:toggle_upload_panel", kwargs={"approval_id": self.instance.approval_id}),
                "hx-target": "#upload_panel",
                "hx-select": "#upload_panel",
            }
        )

        self.fields["end_at"].initial = None
        # Checked by model clean(), avoid double validation message
        self.fields["end_at"].required = False
        self.fields["end_at"].widget = DuetDatePickerWidget(
            {
                "min": self.instance.start_at,
                "max": Prolongation.get_max_end_at(self.instance.start_at),
            }
        )
        self.fields["end_at"].label = f'Du {self.instance.start_at.strftime("%d/%m/%Y")} au'

        if self.data and self.data.get("reason"):
            prolongation_duration = Prolongation.MAX_CUMULATIVE_DURATION[self.data.get("reason")]["label"]
            self.fields["end_at"].help_text = mark_safe(
                f"Date jusqu'à laquelle le PASS IAE doit être prolongé "
                f"<strong>(Durée maximum de 1 an renouvelable jusqu'à { prolongation_duration })</strong>."
                f"<br>"
                f"Au format JJ/MM/AAAA, par exemple 20/12/1978."
            )

        self.fields["email"].widget.attrs.update({"placeholder": "E-mail du prescripteur habilité"})

        # Dynamic : contact fields
        self.fields["require_phone_interview"].widget = forms.CheckboxInput(
            attrs={
                "hx-post": reverse(
                    "approvals:check_contact_details", kwargs={"approval_id": self.instance.approval_id}
                ),
                "hx-target": "#check_contact_details",
                "hx-select": "#check_contact_details",
            }
        )
        self.fields[
            "require_phone_interview"
        ].label = "Demande d'entretien téléphonique pour apporter des explications supplémentaires"
        self.fields["require_phone_interview"].required = False

        # There must be something better : review
        contact_fields_disabled = self.data.get("require_phone_interview", False) not in ("True", "true", "1", "on")

        self.fields["contact_email"].label = "Votre e-mail"
        self.fields["contact_email"].required = False
        self.fields["contact_email"].disabled = contact_fields_disabled
        self.fields["contact_email"].widget.attrs.update({"placeholder": "employeur@email.fr"})
        self.fields["contact_phone"].label = "Votre numéro de téléphone"
        self.fields["contact_phone"].required = False
        self.fields["contact_phone"].disabled = contact_fields_disabled
        self.fields["contact_phone"].widget.attrs.update({"placeholder": "Merci de privilégier votre ligne directe"})

        self.fields["prescriber_organization"].queryset = PrescriberOrganization.objects.none()
        self.fields["prescriber_organization"].label = ""
        self.fields["prescriber_organization"].empty_label = "Sélectionnez l'organisation du prescripteur habilité"
        self.fields["prescriber_organization"].disabled = True
        self.fields["prescriber_organization"].widget.attrs.update(
            {
                "hx-post": reverse(
                    "approvals:check_prescriber_email", kwargs={"approval_id": self.instance.approval_id}
                ),
                "hx-target": "#check_prescriber_email",
                "hx-select": "#check_prescriber_email",
            }
        )

        self.fields["report_file_path"].disabled = not self.siae.can_upload_prolongation_report

        # Dynamic : checking prescriber email
        if kwargs.get("data"):
            if email := kwargs.get("data", {}).get("email"):
                orgs = PrescriberOrganization.objects.filter(
                    members__email=email,
                    members__is_active=True,
                    is_authorized=True,
                )
                self.fields["prescriber_organization"].queryset = orgs
                self.fields["prescriber_organization"].disabled = not orgs
                if orgs.count() == 1:
                    # UI choice : display the select box with a unique selected choice
                    # IMO a simple label would have done the job
                    choices = list(self.fields["prescriber_organization"].widget.choices)
                    choices.pop(0)
                    self.fields["prescriber_organization"].widget.choices = choices

    def clean_prescriber_organization(self):
        prescriber_organization = self.cleaned_data.get("prescriber_organization")
        member_of = self.fields["prescriber_organization"].queryset

        if not prescriber_organization and member_of.count() > 1:
            self.add_error(
                "prescriber_organization",
                "Le prescripteur selectionné fait partie de plusieurs organisations." " Veuillez en sélectionner une.",
            )

        return prescriber_organization

    def clean(self):
        email = self.cleaned_data.get("email")

        if email:
            self.validated_by = User.objects.filter(email=email).first()
            is_authorized_prescriber = self.validated_by and self.validated_by.is_prescriber_with_authorized_org

            if not is_authorized_prescriber:
                # Either does not exist or is not an authorized prescriber
                self.add_error(
                    "email",
                    "Ce prescripteur n'a pas de compte sur les emplois de l'inclusion. "
                    "Merci de renseigner l'e-mail d'un conseiller inscrit sur le service.",
                )

        if self.cleaned_data.get("reason") not in self.reasons_not_need_prescriber_opinion:
            if not email:
                # Prescriber e-mail is mandatory in these cases
                self.add_error("email", "Vous devez choisir un prescripteur habilité")

        if self.cleaned_data.get("require_phone_interview"):
            if not self.cleaned_data.get("contact_email"):
                self.add_error("contact_email", "Veuillez saisir une adresse e-mail de contact")
            if not self.cleaned_data.get("contact_phone"):
                self.add_error("contact_phone", "Veuillez saisir un numéro de téléphone de contact")

        # Prolongation report :
        # - is only mandatory for these reasons
        # - is temporarily limited to AI kind
        if (
            self.cleaned_data.get("reason") in PROLONGATION_REPORT_FILE_REASONS
            and self.siae.can_upload_prolongation_report
        ):
            if not self.cleaned_data.get("report_file_path") or not self.cleaned_data.get("uploaded_file_name"):
                # No visible field for this form field
                raise ValidationError("Vous devez fournir un fichier de bilan renseigné")

    class Meta:
        model = Prolongation
        fields = [
            # Order is important for the template.
            "reason",
            "end_at",
            "require_phone_interview",
            "contact_email",
            "contact_phone",
            "prescriber_organization",
        ]
        widgets = {
            "end_at": DuetDatePickerWidget(),
            "reason": forms.RadioSelect(),
        }
        help_texts = {
            "end_at": mark_safe(
                "Date jusqu'à laquelle le PASS IAE doit être prolongé."
                "<br>"
                "Au format JJ/MM/AAAA, par exemple 20/12/1978."
            ),
        }


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
