"""
Specific widgets used in forms.
"""

from django.utils.translation import gettext_lazy as _
from bootstrap_datepicker_plus import DatePickerInput


class DatePickerField(DatePickerInput):
    """
    Initializes a JS datepicker in a date field.
    Usage:
        end_date = forms.DateField(
            input_formats=DatePickerField().date_format,
            widget=DatePickerField()
        )
    """

    # Date format for Python scripts.
    # /!\ Make sure it matches OPTIONS['format']!!
    DATE_FORMAT = "%d-%m-%Y"

    # http://eonasdan.github.io/bootstrap-datetimepicker/Options/
    OPTIONS = {
        "format": "DD-MM-YYYY", # moment date-time format
        "showClose": True,
        "showClear": True,
        "showTodayButton": True,
        "locale": "fr",
        "tooltips": {
            "today": str(_("Aujourd'hui")),
            "clear": str(_("Effacer")),
            "close": str(_("Fermer")),
            "selectMonth": str(_("Sélectionner un mois")),
            "prevMonth": str(_("Mois précédent")),
            "nextMonth": str(_("Mois suivant")),
            "selectYear": str(_("Sélectionner une année")),
            "prevYear": str(_("Année précédente")),
            "nextYear": str(_("Année suivante")),
            "selectDecade": str(_("Sélectionner une décennie")),
            "prevDecade": str(_("Décennie précédente")),
            "nextDecade": str(_("Décennie suivante")),
            "prevCentury": str(_("Centenaire précédent")),
            "nextCentury": str(_("Centenaire suivant")),
        }
    }

    def __init__(self):
        super().__init__(options=self.OPTIONS)
