{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour {{ user.first_name|title }},

{% if user == report.author %}{{ prescriber.get_full_name }}{% if prescriber_organization %} ({{ prescriber_organization.display_name }}){% endif %} a consulté le bilan d’accompagnement que vous avez rempli le {{ report.created_at|date:"d/m/Y" }}.{% else %}{{ prescriber.get_full_name }}{% if prescriber_organization %} ({{ prescriber_organization.display_name }}){% endif %} a consulté le bilan d’accompagnement rempli le {{ report.created_at|date:"d/m/Y" }} par {{ report.author.get_full_name }}.

Si une autre personne de votre structure suit désormais ce salarié, vous pouvez lui transférer ce message.{% endif %}

Si vous souhaitez en parler avec {{ prescriber.get_full_name }}, vous trouverez ses coordonnées dans l’onglet « Accompagnateurs » de la fiche du salarié :
{{ advisors_url }}
{% endblock body %}
