{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour {{ user.get_full_name }},

Candidature transférée

{{ transferred_by.get_inverted_full_name }} a transféré la candidature de : {{ job_application.job_seeker.get_inverted_full_name }} de la structure {{ origin_company.display_name }} vers la structure {{ target_company.display_name }}.

{% endblock body %}
