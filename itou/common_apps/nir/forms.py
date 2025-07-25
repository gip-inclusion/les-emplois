from django import forms
from django.core.exceptions import NON_FIELD_ERRORS
from django.forms import widgets
from django.urls import reverse
from django.utils.html import format_html

from itou.users.enums import LackOfNIRReason
from itou.utils.validators import validate_nir


class JobSeekerNIRUpdateMixin:
    """Mixin for User's ModelForm

    nir & lack_of_nir_reason must be declared in the form's Meta.fields
    """

    def __init__(self, *args, editor=None, back_url=None, **kwargs):
        super().__init__(*args, **kwargs)

        # A transient checkbox used to collapse optional block
        self.fields["lack_of_nir"] = forms.BooleanField(
            required=False,
            label="Impossible de renseigner le numéro de sécurité sociale",
            widget=widgets.CheckboxInput(
                attrs={
                    "aria-expanded": "false",
                    "aria-controls": "id_lack_of_nir_reason",
                    "data-bs-target": ".lack_of_nir_reason_group",
                    "data-bs-toggle": "collapse",
                    "data-disable-target": "#id_nir",
                }
            ),
        )

        self.fields["nir"] = forms.CharField(
            label="Numéro de sécurité sociale",
            required=False,
            max_length=21,  # 15 + 6 white spaces
            strip=True,
            validators=[validate_nir],
            widget=forms.TextInput(),
        )

        self.fields["lack_of_nir_reason"].label = "Sélectionner un motif"
        # This is a hack to easily tweak this field bootstrap form_group_class
        self.fields["lack_of_nir_reason"].form_group_class = "form-group ms-4 collapse lack_of_nir_reason_group"

        query = {"back_url": back_url} if back_url else {}
        nir_modification_request_link = format_html(
            '<a href="{}">Demander la correction du numéro de sécurité sociale</a>',
            reverse(
                "job_seekers_views:nir_modification_request",
                kwargs={"public_id": self.instance.public_id},
                query=query,
            ),
        )

        if self.initial.get("nir"):
            # Disable NIR editing altogether if the job seeker already has one
            self.fields["nir"].disabled = True
            self.fields["lack_of_nir"].widget = forms.HiddenInput()
            user_instance = self.instance
            if user_instance.pk:
                # These messages should only appear when updating a job seeker
                # and not when creating one
                if not user_instance.is_handled_by_proxy and user_instance != editor:
                    nir_help_text = (
                        "Ce candidat a pris le contrôle de son compte utilisateur. "
                        "Vous ne pouvez pas modifier ses informations."
                    )
                else:
                    nir_help_text = nir_modification_request_link
                self.fields["nir"].help_text = nir_help_text
        else:
            self.fields["nir"].help_text = "Numéro à 15 chiffres."

        if self.initial.get("lack_of_nir_reason") == LackOfNIRReason.NIR_ASSOCIATED_TO_OTHER:
            self.fields["lack_of_nir_reason"].help_text = nir_modification_request_link

        if self["lack_of_nir_reason"].value():
            self.initial["lack_of_nir"] = True
            self.fields["nir"].help_text += (
                " Pour ajouter le numéro de sécurité sociale, "
                "veuillez décocher la case “Impossible de renseigner le numéro de sécurité sociale”."
            )

        if self["lack_of_nir"].value():
            self.fields["nir"].disabled = True
            # Make sure the collapse state is consistent
            self.fields["lack_of_nir"].widget.attrs["aria-expanded"] = "true"
            self.fields["lack_of_nir_reason"].form_group_class += " show"

    def clean_nir(self):
        return self.cleaned_data["nir"].upper().replace(" ", "")

    def clean(self):
        super().clean()
        if self.cleaned_data["lack_of_nir"]:
            if self.cleaned_data.get("lack_of_nir_reason"):
                self.cleaned_data["nir"] = ""
            else:
                self.add_error(
                    "lack_of_nir_reason", forms.ValidationError("Veuillez sélectionner un motif pour continuer")
                )
        else:
            if self.cleaned_data.get("nir"):
                self.cleaned_data["lack_of_nir_reason"] = ""
            elif not self.has_error("nir"):
                self.add_error(
                    "nir",
                    forms.ValidationError("Le numéro de sécurité sociale n'est pas valide"),
                )

    def nir_error(self):
        details = (
            "Pour continuer, veuillez entrer un numéro de sécurité sociale valide ou cocher la "
            f'mention "{self.fields["lack_of_nir"].label}" et sélectionner un motif.'
        )
        if self.has_error(NON_FIELD_ERRORS, code="unique_nir_if_not_empty"):
            title = "Le numéro de sécurité sociale est déjà associé à un autre utilisateur"
        elif self.has_error("nir") or self.has_error("lack_of_nir_reason"):
            title = "Le numéro de sécurité sociale n'est pas valide"
        else:
            return None
        return f"""
            <div class="alert alert-danger" role="alert" tabindex="0" data-emplois-give-focus-if-exist>
                <p>
                    <strong>{title}</strong>
                </p>
                <p class="mb-0">{details}</p>
            </div>
        """
