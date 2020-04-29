import django.forms as forms
import requests
from django.core.validators import URLValidator
from django.utils.translation import gettext_lazy


class ResumeFormMixin(forms.Form):
    """
    Handles resume fields for apply and signup jobseeker forms
    """

    resume_link = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"placeholder": gettext_lazy("Entrez l'adresse de votre CV")})
    )

    def clean_resume_link(self):
        resume_link = self.cleaned_data["resume_link"]

        if resume_link:
            # Check if valid (also on model)
            validator = URLValidator(schemes=["https"])
            validator(resume_link)

            # Check if exists ?
            try:
                requests.head(resume_link, allow_redirects=True)
            except requests.exceptions.RequestException:
                # Catch all
                raise forms.ValidationError(gettext_lazy("Cette URL n'est pas accessible"))

        return resume_link
