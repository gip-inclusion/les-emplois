{% extends "layout/base_email_text_body.md" %}
{% block body %}

Bonjour {{ user.get_full_name }},

Votre demande de réinitialisation de vos paramètres de double authentification a été annulée pour la raison suivante :

{{ msg }}

{% endblock body %}
