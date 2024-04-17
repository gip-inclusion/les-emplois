from django import template
from django.urls import reverse_lazy


register = template.Library()


@register.inclusion_tag("./utils/templatetags/buttons_form.html", takes_context=False)
def itou_buttons_form(
    *,
    primary_disabled=False,
    primary_label="Suivant",
    primary_url=None,
    primary_name=None,
    primary_value=None,
    primary_aria_label="Passer à l’étape suivante",
    reset_url=reverse_lazy("dashboard:index"),
    show_mandatory_fields_mention=True,
    secondary_url=None,
    secondary_aria_label="Retourner à l’étape précédente",
    secondary_name=None,
    secondary_value=None,
    matomo_category=None,
    matomo_action=None,
    matomo_name=None,
    modal_content_save_and_quit=False,
):
    """
    Render buttons on forms.

    **Tag name**::

        itou_buttons_form

    **Parameters**::

        primary_label
            The label for the primary button.

        primary_url
            The url for the primary button. If True, display href as a button, instead of a submit button.

        primary_aria_label
            The ARIA label for the primary button.

        secondary_url
            The url for the secondary button.

        secondary_aria_label
            The ARIA label for the secondary button.

        reset_url
            The url for the reset button.

        matomo_category & matomo_action & matomo_name
            If set together, the buttons will send a matomo event on click.

        show_mandatory_fields_mention
            If True, show the mention "champs obligatoires" on the form.

        primary_disabled
            If True, the primary button is disabled.

        primary_name & primary_value
            If set together, the name and value for the primary button.

        secondary_name & secondary_value
            If set together, the name and value for the secondary button.

        modal_content_save_and_quit
            If set, force alternate modal content for the save and quit button.

    **Usage**::

        {% itou_buttons_form  %}

    **Example**::

        {% itou_buttons_form show_mandatory_fields_mention=False %}
    """

    matomo_values = (matomo_category, matomo_action, matomo_name)
    if any(matomo_values) and not all(matomo_values):
        raise ValueError("Matomo values are all or nothing")

    return {
        "show_mandatory_fields_mention": show_mandatory_fields_mention,
        "primary_aria_label": primary_aria_label,
        "primary_disabled": primary_disabled,
        "primary_label": primary_label,
        "primary_name": primary_name,
        "primary_value": primary_value,
        "primary_url": primary_url,
        "reset_url": reset_url,
        "secondary_url": secondary_url,
        "secondary_aria_label": secondary_aria_label,
        "secondary_name": secondary_name,
        "secondary_value": secondary_value,
        "matomo_category": matomo_category,
        "matomo_action": matomo_action,
        "matomo_name": matomo_name,
        "modal_content_save_and_quit": modal_content_save_and_quit,
    }
