from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _


class EditUserInfoForm(forms.ModelForm):
    """
    Edit a user profile.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.is_job_seeker:
            del self.fields["birthdate"]
        else:
            self.fields["phone"].required = True
            self.fields["birthdate"].required = True
            self.fields["birthdate"].input_formats = settings.DATE_INPUT_FORMATS

    class Meta:
        model = get_user_model()
        fields = ["birthdate", "phone"]
        help_texts = {
            "birthdate": _("Au format jj/mm/aaaa, par exemple 20/12/1978"),
            "phone": _("Par exemple 0610203040"),
        }
