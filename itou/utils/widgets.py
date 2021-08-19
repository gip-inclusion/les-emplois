"""
Specific widgets used in forms.
"""
import datetime

from bootstrap_datepicker_plus import DatePickerInput
from django import forms

from itou.utils.validators import get_max_birthdate, get_min_birthdate


class DuetDatePickerWidget(forms.DateInput):
    """
    Custom form widget for Duet Date Picker.

    Dates can be passed as date objects or as strings (YYYY-MM-DD).
    E.g.:
        my_date = forms.DateField(initial=datetime.date.today())
        my_date = forms.DateField(initial="2021-07-18")

    See:
        - https://duetds.github.io/date-picker/
        - https://github.com/duetds/date-picker
    """

    INPUT_DATE_FORMAT = "%Y-%m-%d"

    template_name = "utils/widgets/duet_date_picker_widget.html"

    class Media:
        css = {
            "all": ("https://cdn.jsdelivr.net/npm/@duetds/date-picker@1.4.0/dist/duet/themes/default.css",),
        }
        js = (
            "https://cdn.jsdelivr.net/npm/@duetds/date-picker@1.4.0/dist/duet/duet.js",
            "js/duet_date_picker_widget.js",
        )

    def format_value(self, value):
        """
        Check that dates are in IS0-8601 format: YYYY-MM-DD.
        """
        # Dates can be passed as date objects…
        if isinstance(value, datetime.date):
            return value.strftime(self.INPUT_DATE_FORMAT)
        # …or as strings (YYYY-MM-DD).
        if isinstance(value, str):
            try:
                datetime.datetime.strptime(value, self.INPUT_DATE_FORMAT)
                return value
            except ValueError:
                raise ValueError(f'Date format of {value} must be "{self.INPUT_DATE_FORMAT}".')
        return value

    def build_attrs(self, base_attrs, extra_attrs=None):
        attrs = super().build_attrs(base_attrs, extra_attrs=extra_attrs)
        # Allow to pass the `min` attribute either as a date object or as a string.
        min_attr = attrs.get("min")
        if min_attr:
            attrs["min"] = self.format_value(min_attr)
        # Allow to pass the `max` attribute either as a date object or as a string.
        max_attr = attrs.get("max")
        if max_attr:
            attrs["max"] = self.format_value(max_attr)
        return attrs

    @classmethod
    def max_birthdate(cls):
        return get_max_birthdate()

    @classmethod
    def min_birthdate(cls):
        return get_min_birthdate()


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
