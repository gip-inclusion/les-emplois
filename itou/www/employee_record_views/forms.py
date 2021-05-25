from django import forms
from django.urls import reverse_lazy

from itou.asp.models import Commune
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

    COMMUNE_AUTOCOMPLETE_SOURCE_URL = reverse_lazy("autocomplete:communes")

    READ_ONLY_FIELDS = []
    REQUIRED_FIELDS = [
        "title",
        "first_name",
        "last_name",
        "birthdate",
        "birth_country",
    ]

    insee_commune = forms.CharField(
        label="Commune de naissance",
        required=False,
        help_text="La commune de naissance ne doit être saisie que lorsque le salarié est né en France",
        widget=forms.TextInput(
            attrs={
                "class": "js-commune-autocomplete-input form-control",
                "data-autocomplete-source-url": COMMUNE_AUTOCOMPLETE_SOURCE_URL,
                "data-autosubmit-on-enter-pressed": 0,
                "placeholder": "Nom de la commune",
                "autocomplete": "off",
            }
        ),
    )
    insee_commune_code = forms.CharField(
        required=False, widget=forms.HiddenInput(attrs={"class": "js-commune-autocomplete-hidden"})
    )

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

        if hasattr(self, "instance"):
            # Init for with ASP commune
            if self.instance.birth_place:
                self.initial[
                    "insee_commune"
                ] = f"{self.instance.birth_place.name} ({self.instance.birth_place.department_code})"
                self.initial["insee_commune_code"] = self.instance.birth_place.code

    def clean(self):
        super().clean()

        commune_code = self.cleaned_data["insee_commune_code"]

        if commune_code:
            self.cleaned_data["birth_place"] = Commune.objects.by_insee_code(commune_code)

    class Meta:
        model = User
        fields = [
            "title",
            "first_name",
            "last_name",
            "birthdate",
            "insee_commune",
            "insee_commune_code",
            "birth_place",
            "birth_country",
        ]


class NewEmployeeRecordStep2(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        for field_name in ["phone", "email"]:
            self.fields[field_name].widget.attrs["readonly"] = True
            self.fields[field_name].help_text = "Non modifiable"

    class Meta:
        model = User
        fields = [
            "address_line_1",
            "address_line_2",
            "post_code",
            "city",
            "phone",
            "email",
        ]
