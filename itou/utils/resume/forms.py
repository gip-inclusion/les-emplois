import django.forms as forms
from django.utils.translation import gettext_lazy


class ResumeFormMixin(forms.Form):
    """
    Handles resume fields for apply and signup jobseeker forms
    """

    resume_link = forms.URLField(
        label=gettext_lazy("Lien vers un CV"),
        help_text=gettext_lazy("Vous pouvez saisir un lien vers un CV de votre choix (CVDesignR, ...)"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": gettext_lazy("Entrez l'adresse de votre CV")}),
    )
