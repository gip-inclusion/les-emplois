from django import forms

# from itou.utils.widgets import DatePickerField
from itou.utils.widgets import DuetDatePickerWidget


class DuetDatePickerForm(forms.Form):
    """
    Test Duet Date Picker.
    """

    dummy = forms.CharField(
        label="Dummy field",
        required=False,
        help_text="Pour voir le look avec Duet Date Picker.",
    )

    start_date = forms.DateField(
        label="Début",
        required=True,
        initial="2021-07-18",
        widget=DuetDatePickerWidget(attrs={"min": "2021-06-18", "max": "2021-10-18"}),
        help_text="Au format JJ/MM/AAAA, par exemple 20/12/1978.",
    )

    end_date = forms.DateField(
        label="Fin",
        required=True,
        widget=DuetDatePickerWidget(),
        help_text="Au format JJ/MM/AAAA, par exemple 20/12/1978.",
    )
