{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour,

Une nouvelle demande de régularisation NIR est à traiter dans l’admin des Emplois :
{{ request_url }}

Cordialement,
{% endblock body %}
