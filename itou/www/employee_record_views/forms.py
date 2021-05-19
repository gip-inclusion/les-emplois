from django import forms

from itou.employee_record.models import EmployeeRecord
from itou.users.models import User
from itou.utils.widgets import DatePickerField


class SelectEmployeeRecordStatusForm(forms.Form):

    # The user is only able to select a subset of the possible
    # employee record statuses.
    # The other ones are internal only.
    STATUSES = [
        EmployeeRecord.Status.NEW,
        EmployeeRecord.Status.SENT,
        EmployeeRecord.Status.REJECTED,
        EmployeeRecord.Status.PROCESSED,
    ]

    STATUS_CHOICES = [(choice.name, choice.label) for choice in STATUSES]
    status = forms.ChoiceField(
        widget=forms.RadioSelect(),
        choices=STATUS_CHOICES,
        initial=EmployeeRecord.Status.NEW,
    )


class NewEmployeeRecordStep1(forms.ModelForm):

    READ_ONLY_FIELDS = []
    REQUIRED_FIELDS = [
        "title",
        "first_name",
        "last_name",
        "birthdate",
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in self.REQUIRED_FIELDS:
            self.fields[field_name].required = True

        self.fields["birthdate"].widget = DatePickerField(
            {
                "viewMode": "years",
                "minDate": DatePickerField.min_birthdate().strftime("%Y/%m/%d"),
                "maxDate": DatePickerField.max_birthdate().strftime("%Y/%m/%d"),
                "useCurrent": False,
                "allowInputToggle": False,
            }
        )
        self.fields["birthdate"].input_formats = [DatePickerField.DATE_FORMAT]

    class Meta:
        model = User
        fields = [
            "title",
            "first_name",
            "last_name",
            "birthdate",
            # "birth_place",
            "birth_country",
        ]
