import django.forms as forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy


class ResumeFormMixin(forms.Form):
    """
    Handles resume fields for apply and signup jobseeker forms
    """

    resume_link = forms.URLField(
        label=gettext_lazy("Indiquez le lien d'un CV existant"),
        help_text=gettext_lazy("Vous pouvez saisir un lien vers le CV de votre choix (CVDesignR, ...)"),
        required=False,
        widget=forms.TextInput(attrs={"placeholder": gettext_lazy("https://www.mon_cv.fr/dfROS")}),
    )

    class Meta:
        fields = [
            "resume_link",
        ]
