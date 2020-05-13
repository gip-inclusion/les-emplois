from django import forms
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy

from itou.utils.address.forms import AddressFormMixin
from itou.utils.resume.forms import ResumeFormMixin
from itou.utils.widgets import DatePickerField


class EditUserInfoForm(AddressFormMixin, ResumeFormMixin, forms.ModelForm):
    """
    Edit a user profile.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.is_job_seeker:
            del self.fields["birthdate"]
            del self.fields["pole_emploi_id"]
            del self.fields["lack_of_pole_emploi_id_reason"]
            del self.fields["resume_link"]
        else:
            self.fields["phone"].required = True
            self.fields["birthdate"].required = True
            self.fields["birthdate"].widget = DatePickerField(
                {
                    "viewMode": "years",
                    "minDate": DatePickerField.min_birthdate().strftime("%Y"),
                    "maxDate": DatePickerField.max_birthdate().strftime("%Y"),
                }
            )
            self.fields["birthdate"].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = get_user_model()
        fields = [
            "birthdate",
            "phone",
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "city_name",
            "pole_emploi_id",
            "lack_of_pole_emploi_id_reason",
            "resume_link",
        ]
        help_texts = {
            "birthdate": gettext_lazy("Au format jj-mm-aaaa, par exemple 20-12-1978"),
            "phone": gettext_lazy("Par exemple 0610203040"),
        }

    def clean(self):
        super().clean()
        if self.instance.is_job_seeker:
            self._meta.model.clean_pole_emploi_fields(
                self.cleaned_data["pole_emploi_id"], self.cleaned_data["lack_of_pole_emploi_id_reason"]
            )
