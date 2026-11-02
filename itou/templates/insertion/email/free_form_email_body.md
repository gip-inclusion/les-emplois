{% extends "layout/base_email_text_body.md" %}
{% block body %}
{{ body_message }}
{% endblock body %}

{% block signature %}
{% include "layout/includes/base_email_signature_for_inbound_parsing.txt" with itou_environment=itou_environment base_url=base_url sender_name=sender_name display_attachments_warning=display_attachments_warning only %}
{% endblock signature%}
