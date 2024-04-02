from django import template
from django.template.defaultfilters import title

from itou.common_apps.address.departments import department_from_postcode


register = template.Library()


def display_insee_city(city):
    return f"{city.department} - {city.name}"


@register.simple_tag
def profile_city_display(profile):
    if profile.hexa_commune:
        if profile.hexa_commune.city:
            return display_insee_city(profile.hexa_commune.city)
        display_name = title(profile.hexa_commune.name.replace("E__ARRONDISSEMENT", "ᵉ"))
        return f"{department_from_postcode(profile.hexa_commune.code)} - {display_name}"
    if profile.user.insee_city:
        return display_insee_city(profile.user.insee_city)
    parts = []
    if profile.user.post_code:
        parts.append(department_from_postcode(profile.user.post_code))
    if profile.user.city:
        parts.append(profile.user.city)
    if parts:
        return " - ".join(parts)
    return "Ville non renseignée"
