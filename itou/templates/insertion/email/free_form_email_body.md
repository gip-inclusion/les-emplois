{% autoescape off %}

{% block body %}{% endblock %}

{% include "layout/base_email_signature_for_inbound_parsing.txt" with itou_environment=itou_environment base_url=base_url sender_name=sender_name display_attachment_warning=display_attachment_warning only %}
{% endautoescape %}
