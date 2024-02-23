from django import template


register = template.Library()


@register.inclusion_tag("./utils/templatetags/buttons_form.html", takes_context=False)
def itou_buttons_form(**kwargs):
    """
    Render buttons on forms.

    **Tag name**::

        itou_buttons_form

    **Parameters**::

        primary_label
            The label for the primary button.
            Default: "Suivant"

        primary_url
            The url for the primary button. If True, display href as a button, instead of a submit button.
            Optional
            Default: None

        secondary_url
            The url for the secondary button.
            Optional
            Default: None

        reset_url
            The url for the reset button. If True, display href link, whether reset_submit exists or not.
            Optional
            Default: 'dashboard:index'

        reset_submit
            display a reset button, if True and reset_url is not set.
            Optional
            Default: False

        matomo_category & matomo_action & matomo_name
            If set together, the buttons will send a matomo event on click.
            Optional
            Default: None

        show_mandatory_fields_mention
            if True, show the mention "champs obligatoires" on the form.
            Default: True

        primary_disabled
            if True, the primary button is disabled.
            Optional
            Default: False

        primary_name & primary_value
            If set together, the name and value for the primary button.
            Optional
            Default: None

        secondary_name & secondary_value
            If set together, the name and value for the secondary button.
            Optional
            Default: None

        modal_content_save_and_quit
            if set, force alternate modal content for the save and quit button.
            Optional
            Default: None


    **Usage**::

        {% itou_buttons_form  %}

    **Example**::

        {% itou_buttons_form reset_submit=True %}
    """
    if kwargs.get("primary_label") is None:
        kwargs["primary_label"] = "Suivant"
    if kwargs.get("show_mandatory_fields_mention") is None:
        kwargs["show_mandatory_fields_mention"] = True

    return {**kwargs}
