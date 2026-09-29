{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour {{ user.get_full_name }},

Votre candidature a été acceptée par {{ job_application.to_company.display_name }}.

{% if job_application.answer %}
**Message de l'entreprise** :

{{ job_application.answer }}
{% endif %}
{% endblock body %}
