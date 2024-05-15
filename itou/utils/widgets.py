"""
Specific widgets used in forms.
"""

import datetime
import operator

from django import forms
from django.conf import settings
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
        query = Q(**{f"{field_name}__in": selected_choices})
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


class AddressAutocompleteWidget(RemoteAutocompleteSelect2Widget):
    # Be careful when using this widget because it requires the following fields to be included in the form:
    #
    # "address_line_1",
    # "address_line_2",
    # "post_code",
    # "city",
    # "insee_code",
    # "ban_api_resolved_address",

    def __init__(self, *args, one_choice_selected=None, **kwargs):
        super().__init__(*args, **kwargs)

        choices = None

        # Build the choices by hand
        if one_choice_selected is not None:
            choices = [(0, one_choice_selected)]
            self.choices = choices

    class Media:
        js = ["js/address_autocomplete_fields.js"]

    def build_attrs(self, base_attrs, extra_attrs=None):
        return super().build_attrs(base_attrs, extra_attrs=extra_attrs) | {
            "data-ajax--url": f"{settings.API_BAN_BASE_URL}/search/",
            "data-minimum-input-length": 3,
            "data-placeholder": "Ex. 102 Quai de Jemmapes 75010 Paris",
        }


class JobSeekerAddressAutocompleteWidget(AddressAutocompleteWidget):
    # Be careful when using this widget as it needs fields present in the form it is included into
    #
    # "address_line_1",
    # "address_line_2",
    # "post_code",
    # "city",
    # "insee_code",
    # "ban_api_resolved_address",

    def __init__(self, *args, initial_data=None, job_seeker=None, **kwargs):
        address_choice = None

        # The following code is required as we are using a Select2 version not tied to a model
        # in order to perform Ajax calls, but we need it to mimick the behavior of a model field
        if initial_data and "ban_api_resolved_address" in initial_data:
            # The ban_api_resolved_address field is populated using javascript (after selecting an address).
            # So if it present in the submitted data, it means that the user did a select2 choice
            # so we should refill and populate the choosen address in the select2 field if there was a form error
            address_choice = initial_data["ban_api_resolved_address"]
        elif job_seeker:
            # If there is no ban_api_resolvedaddress_field, let's fill the form with the geocoding_address saved
            # on the job_seeker profile
            if job_seeker.address_line_1:
                address_choice = job_seeker.geocoding_address

        super().__init__(*args, one_choice_selected=address_choice, **kwargs)

    class Media:
        js = ["js/address_autocomplete_fields.js"]
