"""
Specific widgets used in forms.
"""

from bootstrap_datepicker_plus import DatePickerInput
from django import forms

from itou.utils.validators import get_max_birthdate, get_min_birthdate


class DatePickerField(DatePickerInput):
    """
    Initializes a JS datepicker in a date field.
    Usage:
        end_date = forms.DateField(
            input_formats=[DatePickerField.DATE_FORMAT],
            widget=DatePickerField()
        )
    """

    # /!\ Make sure it matches OPTIONS['format']!!
    DATE_FORMAT = "%d/%m/%Y"

    # http://eonasdan.github.io/bootstrap-datetimepicker/Options/
    OPTIONS = {
        "format": "DD/MM/YYYY",  # moment date-time format
        "showClose": True,
        "showClear": True,
        "showTodayButton": True,
        "locale": "fr",
        "tooltips": {
            "today": "Aujourd'hui",
            "clear": "Effacer",
            "close": "Fermer",
            "selectMonth": "Sélectionner un mois",
            "prevMonth": "Mois précédent",
            "nextMonth": "Mois suivant",
            "selectYear": "Sélectionner une année",
            "prevYear": "Année précédente",
            "nextYear": "Année suivante",
            "selectDecade": "Sélectionner une décennie",
            "prevDecade": "Décennie précédente",
            "nextDecade": "Décennie suivante",
            "prevCentury": "Centenaire précédent",
            "nextCentury": "Centenaire suivant",
        },
    }

    def __init__(self, options={}):
        options = {**self.OPTIONS, **options}
        super().__init__(attrs={"placeholder": "JJ/MM/AAAA"}, options=options)

    @classmethod
    def max_birthdate(cls):
        return get_max_birthdate()

    @classmethod
    def min_birthdate(cls):
        return get_min_birthdate()


class SwitchCheckboxWidget(forms.CheckboxInput):
    """
    Display a switch button instead of a checkbox.
    See https://getbootstrap.com/docs/4.4/components/forms/#switches

    Usage :
    - Add it to a form
    - Add the "custom-control custom-switch" classes to the div containing the input.

    Example:
    ```
    # Form
    my_field = forms.BooleanField(widget=SwitchCheckboxWidget())

    # Template
    {% bootstrap_form form field_class="custom-control custom-switch" %}
    ```
    """

    template_name = "utils/widgets/switch_checkbox_option.html"


class MultipleSwitchCheckboxWidget(forms.CheckboxSelectMultiple):
    """
    Display switch buttons instead of checkboxes.
    See https://getbootstrap.com/docs/4.4/components/forms/#switches
    """

    option_template_name = "utils/widgets/switch_checkbox_option.html"
