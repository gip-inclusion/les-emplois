{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour {{ contact.first_name|title }}, bonjour {{ prescriber.first_name|title }},

{% if contact == report.author %}{{ contact.first_name|title }}, {{ prescriber.get_full_name }} ({{ prescriber_organization.display_name }}), en copie de ce message, a consulté le bilan d’accompagnement que vous avez rempli le {{ report.created_at|date:"d/m/Y" }}, et souhaite en parler de vive voix avec vous, pour évoquer le bilan et travailler la suite du parcours.{% else %}{{ contact.first_name|title }}, {{ prescriber.get_full_name }} ({{ prescriber_organization.display_name }}), en copie de ce message, a consulté le bilan d’accompagnement rempli le {{ report.created_at|date:"d/m/Y" }} par {{ report.author.get_full_name }}, qui a quitté votre structure, et souhaite en parler de vive voix avec vous, pour évoquer le bilan et travailler la suite du parcours.

Si une autre personne de votre structure suit désormais ce parcours, vous pouvez lui transférer ce message.{% endif %}

Voici vos coordonnées respectives :

**{{ contact.get_full_name }}**, {{ report.company.display_name }}
{% if contact.phone %}Téléphone : {{ contact.phone }}
{% elif report.company.phone %}Téléphone de la structure : {{ report.company.phone }}
{% endif %}Adresse e-mail : {{ contact.email }}

**{{ prescriber.get_full_name }}**, {{ prescriber_organization.display_name }}
Téléphone : {{ prescriber.phone }}
Adresse e-mail : {{ prescriber.email }}

N’hésitez pas à vous appeler ou à vous écrire : utilisez « Répondre à tous ».

Consulter le bilan :
{{ report_url }}
{% endblock body %}
