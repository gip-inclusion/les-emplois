{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour,

Suite aux manquements constatés lors du dernier contrôle a posteriori des auto-prescriptions réalisées dans votre SIAE, nous avons décidé de ne pas appliquer de sanction. Vous trouverez ci-dessous le détail de cette décision :

{{ sanctions.no_sanction_reason }}

Cordialement,
{% endblock %}
