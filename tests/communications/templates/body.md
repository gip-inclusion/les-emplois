{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour {{ user.get_full_name }},

Ceci est un email de test.
{% endblock body %}
