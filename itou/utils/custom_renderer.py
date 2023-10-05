from django.forms import CheckboxInput
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django_bootstrap5.css import merge_css_classes
from django_bootstrap5.renderers import FieldRenderer
from django_bootstrap5.text import text_value


class CustomFieldRenderer(FieldRenderer):
    def render(self):  # noqa: PLR0912
        if self.field.name in self.exclude.replace(" ", "").split(","):
            return mark_safe("")
        if self.field.is_hidden:
            return text_value(self.field)

        field = self.get_field_html()

        if self.field_before_label():
            label = self.get_label_html()
            field = field + label
            label = mark_safe("")
            horizontal_class = merge_css_classes(self.horizontal_field_class, self.horizontal_field_offset_class)
        else:
            label = self.get_label_html(horizontal=self.is_horizontal)
            horizontal_class = self.horizontal_field_class

        help = self.get_help_html()
        errors = self.get_errors_html()

        if self.is_form_control_widget():
            if self.addon_before_class is None:
                addon_before = self.addon_before
            else:
                addon_before = (
                    format_html('<span class="{}">{}</span>', self.addon_before_class, self.addon_before)
                    if self.addon_before
                    else ""
                )
            if self.addon_after_class is None:
                addon_after = self.addon_after
            else:
                addon_after = (
                    format_html('<span class="{}">{}</span>', self.addon_after_class, self.addon_after)
                    if self.addon_after
                    else ""
                )
            if addon_before or addon_after:
                classes = "input-group"
                if self.server_side_validation and self.get_server_side_validation_classes():
                    classes = merge_css_classes(classes, "has-validation")
                    errors = errors or mark_safe("<div></div>")
                field = format_html(
                    '<div class="{}">{}{}{}{}</div>', classes, addon_before, field, addon_after, errors
                )
                errors = ""

        if isinstance(self.widget, CheckboxInput):
            field = format_html('<div class="{}">{}{}{}</div>', self.get_checkbox_classes(), field, errors, help)
            errors = ""
            help = ""

        field_with_errors_and_help = format_html("{}{}{}", field, errors, help)

        if self.is_horizontal:
            field_with_errors_and_help = format_html(
                '<div class="{}">{}</div>', horizontal_class, field_with_errors_and_help
            )

        # ADDED PART ###############################################
        # Workaround to fix bug: https://github.com/zostera/django-bootstrap5/issues/287
        if self.field_class:
            field_with_errors_and_help = format_html(
                '<div class="{}">{}</div>', self.field_class, field_with_errors_and_help
            )
        ############################################################

        return format_html(
            '<div class="{wrapper_classes}">{label}{field_with_errors_and_help}</div>',
            wrapper_classes=self.get_wrapper_classes(),
            label=label,
            field_with_errors_and_help=field_with_errors_and_help,
        )

    def get_server_side_validation_classes(self):
        """Return CSS classes for server-side validation."""
        if self.field_errors:
            return "is-invalid"
        # Removed from parent class
        # elif self.field.form.is_bound:
        #    return "is-valid"
        return ""
