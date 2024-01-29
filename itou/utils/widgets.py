"""
Specific widgets used in forms.
"""

import datetime
import operator

from django import forms
from django.contrib.gis.forms import widgets as gis_widgets
from django.db.models import Q
from django.forms.models import ModelChoiceIterator
from django_select2.forms import Select2Widget

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


class RemoteAutocompleteSelect2Widget(Select2Widget):
    def __init__(self, *args, label_from_instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        # This function must match what the autocomplete view specified via data-ajax--url returns as text
        if label_from_instance is None:
            label_from_instance = operator.methodcaller("autocomplete_display")
        self.label_from_instance = label_from_instance

    # This comes directly from django_select2's ModelSelect2Mixin
    # and avoid the inclusion of all the possible values in the rendered HTML
    def optgroups(self, name, value, attrs=None):
        """Return only selected options and set QuerySet from `ModelChoicesIterator`."""
        default = (None, [], 0)
        groups = [default]
        has_selected = False
        selected_choices = {str(v) for v in value}
        if not self.is_required and not self.allow_multiple_selected:
            default[1].append(self.create_option(name, "", "", False, 0))
        if not isinstance(self.choices, ModelChoiceIterator):
            return super().optgroups(name, value, attrs=attrs)
        selected_choices = {c for c in selected_choices if c not in self.choices.field.empty_values}
        field_name = self.choices.field.to_field_name or "pk"
        query = Q(**{"%s__in" % field_name: selected_choices})
        for obj in self.choices.queryset.filter(query):
            option_value = self.choices.choice(obj)[0]
            option_label = self.label_from_instance(obj)

            selected = str(option_value) in value and (has_selected is False or self.allow_multiple_selected)
            if selected is True and has_selected is False:
                has_selected = True
            index = len(default[1])
            subgroup = default[1]
            subgroup.append(self.create_option(name, option_value, option_label, selected_choices, index))
        return groups
