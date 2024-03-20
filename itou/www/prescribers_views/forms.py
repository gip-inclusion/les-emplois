from django import forms

from itou.prescribers.enums import PrescriberOrganizationKind
from itou.prescribers.models import PrescriberOrganization


class EditPrescriberOrganizationForm(forms.ModelForm):
    class Meta:
        model = PrescriberOrganization
        fields = [
            "siret",
            "name",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "department",
            "phone",
            "email",
            "website",
            "description",
        ]
        help_texts = {
            "siret": "Le numéro SIRET contient 14 chiffres.",
            "description": "Texte de présentation de votre structure.",
            "website": "Votre site web doit commencer par http:// ou https://",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        required_fields = ["address_line_1", "post_code", "city", "department"]
        for required_field in required_fields:
            self.fields[required_field].required = True

        if self.instance.kind == PrescriberOrganizationKind.PE:
            # Do not edit the name of a Pôle emploi agency.
            del self.fields["name"]
            # Duplicates are identified through SAFIR code which makes the SIRET not required.
            del self.fields["siret"]
        elif not self.instance.siret:
            # Ask SIRET for organizations created before it became required in the signup process.
            # This should be temporary until all orgs have a SIRET.
            self.fields["siret"].required = True
        else:
            # Display the non-editable SIRET. This is an arbitrary choice that
            # can be changed once all non-PE orgs have a SIRET.
            self.fields["siret"].required = False
            self.fields["siret"].widget.attrs["readonly"] = True

        # PE users often mistakenly edit this page, to the point where the
        # support asked to disable it, and have them reach out in case of
        # changes.
        if self.instance.kind == PrescriberOrganizationKind.PE:
            for field in self.fields.values():
                field.disabled = True

    def clean_siret(self):
        siret = self.cleaned_data["siret"]
        if (
            siret
            and PrescriberOrganization.objects.exclude(pk=self.instance.pk)
            .filter(siret=siret, kind=self.instance.kind)
            .exists()
        ):
            error = f"Ce SIRET est déjà utilisé avec le type {self.instance.kind}."
            raise forms.ValidationError(error)
        return siret

    def save(self, commit=True):
        prescriber_org = super().save(commit=False)
        if commit:
            prescriber_org.set_coords()
            prescriber_org.save()
        return prescriber_org
