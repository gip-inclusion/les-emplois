{% autoescape off %}

{% block body %}{% endblock %}

{% include "layout/includes/base_email_signature.txt" with itou_environment=itou_environment base_url=base_url display_gdpr=True only %}
{% endautoescape %}
