"""
Specific widgets used in forms.
"""
from bootstrap_datepicker_plus import DatePickerInput
from django.utils.translation import gettext_lazy

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
            "today": str(gettext_lazy("Aujourd'hui")),
            "clear": str(gettext_lazy("Effacer")),
            "close": str(gettext_lazy("Fermer")),
            "selectMonth": str(gettext_lazy("Sélectionner un mois")),
            "prevMonth": str(gettext_lazy("Mois précédent")),
            "nextMonth": str(gettext_lazy("Mois suivant")),
            "selectYear": str(gettext_lazy("Sélectionner une année")),
            "prevYear": str(gettext_lazy("Année précédente")),
            "nextYear": str(gettext_lazy("Année suivante")),
            "selectDecade": str(gettext_lazy("Sélectionner une décennie")),
            "prevDecade": str(gettext_lazy("Décennie précédente")),
            "nextDecade": str(gettext_lazy("Décennie suivante")),
            "prevCentury": str(gettext_lazy("Centenaire précédent")),
            "nextCentury": str(gettext_lazy("Centenaire suivant")),
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
