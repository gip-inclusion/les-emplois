from django import forms
from django.utils.translation import gettext as _, gettext_lazy

from itou.prescribers.models import PrescriberOrganization


class EditPrescriberOrganizationForm(forms.ModelForm):
    """
    Edit a prescriber organization.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.is_authorized:
            # Do not edit the name of an authorized prescriber organization.
            del self.fields["name"]

        if self.instance.kind == self.instance.Kind.PE:
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
        fields = ["siret", "name", "phone", "email", "website", "description"]
        help_texts = {
            "siret": gettext_lazy("Le numéro SIRET contient 14 chiffres."),
            "phone": gettext_lazy("Par exemple 0610203040"),
            "description": gettext_lazy("Texte de présentation de votre structure."),
            "website": gettext_lazy("Votre site web doit commencer par http:// ou https://"),
        }

    def clean_siret(self):
        siret = self.cleaned_data["siret"]
        if siret and PrescriberOrganization.objects.exclude(pk=self.instance.pk).filter(siret=siret).exists():
            error = _("Ce SIRET est déjà utilisé.")
            raise forms.ValidationError(error)
        return siret
