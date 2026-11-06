{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour,

---
E-mail envoyé depuis la Plateforme de l’inclusion. Répondez directement à cet e-mail pour répondre à {{ sender.get_full_name }} ({{ sender_organization }}).

---
{{ body }}
{% endblock %}
