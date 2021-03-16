from django import forms
from django.utils.translation import gettext as _, gettext_lazy

from itou.prescribers.models import PrescriberOrganization


class EditPrescriberOrganizationForm(forms.ModelForm):
    """
    Edit a prescriber organization.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        required_fields = ["address_line_1", "post_code", "city", "department"]
        for required_field in required_fields:
            self.fields[required_field].required = True

        if self.instance.is_kind_pe:
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
            "siret": gettext_lazy("Le numéro SIRET contient 14 chiffres."),
            "phone": gettext_lazy("Par exemple 0610203040"),
            "description": gettext_lazy("Texte de présentation de votre structure."),
            "website": gettext_lazy("Votre site web doit commencer par http:// ou https://"),
        }

    def clean_siret(self):
        siret = self.cleaned_data["siret"]
        if (
            siret
            and PrescriberOrganization.objects.exclude(pk=self.instance.pk)
            .filter(siret=siret, kind=self.instance.kind)
            .exists()
        ):
            error = _("Ce SIRET est déjà utilisé.")
            raise forms.ValidationError(error)
        return siret

    def save(self, commit=True):
        prescriber_org = super().save(commit=False)
        if commit:
            prescriber_org.set_coords(prescriber_org.geocoding_address, post_code=prescriber_org.post_code)
            prescriber_org.save()
        return prescriber_org
