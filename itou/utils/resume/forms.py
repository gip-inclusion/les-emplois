import django.forms as forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy


class ResumeFormMixin(forms.Form):
    """
    Handles resume fields for apply and signup jobseeker forms
    """

    typeform_response_id = forms.CharField(
        widget=forms.HiddenInput(attrs={"id": "typeform_response_id"}), required=False
    )

    resume_link = forms.URLField(
        label=gettext_lazy("Lien vers un CV"),
        help_text=gettext_lazy("Vous pouvez saisir un lien vers un CV de votre choix (CVDesignR, ...)"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": gettext_lazy("Entrez l'adresse de votre CV")}),
    )

    class Meta:
        fields = [
            "typeform_response_id",
            "resume_link",
        ]
