{% autoescape off %}

{% block body %}{% endblock %}

{% include "layout/includes/base_email_signature.txt" with display_gdpr=True %}
{% endautoescape %}
