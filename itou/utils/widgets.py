"""
Specific widgets used in forms.
"""
import datetime

from django import forms
from django.contrib.gis.forms import widgets as gis_widgets

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

    def format_value(self, value):
        """
        Check that dates are in IS0-8601 format: YYYY-MM-DD.
        """
        if isinstance(value, datetime.date):
            return value.strftime(self.INPUT_DATE_FORMAT)
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
        # Remove the `form-control` class inserted by `django-bootstrap4` to avoid
        # breaking the layout.
        attrs["class"] = attrs.get("class", "").replace("form-control", "").strip()
        try:
            attrs["identifier"] = attrs.pop("id")
        except KeyError:
            pass
        return attrs

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


class OSMWidget(gis_widgets.OSMWidget):
    # https://docs.djangoproject.com/en/4.1/ref/contrib/gis/forms-api/#widget-classes
    # We copied the html to include the nonce attribute
    # We need to set the widget in the admin formfield_for_dbfield function
    # because widget render does not access to the request context
    # (see itou.utils.admin.ItouGISMixin)
    template_name = "utils/widgets/csp_proof_openlayers-osm.html"

    class Media:
        css = {
            "all": ["vendor/ol/ol.css"],
        }
        js = ["vendor/ol/ol.js"]
