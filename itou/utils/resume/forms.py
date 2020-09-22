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

    class Meta:
        fields = [
            "typeform_response_id",
        ]
