{% extends "layout/base_email_text_body.md" %}
{% block body %}
Un administrateur vous a retiré les droits d'administrateur d'une structure sur {% brand %}

Organisation :

- Nom : {{ structure.display_name }}
- Type : {{ structure.kind }}
{% if structure.email  %}- Email de contact : {{ structure.email }}{% endif %}{# Institutions don't have a contact email address. #}

Si vous estimez qu'il peut s'agir d'une erreur, contactez un des administrateurs cette structure sur {% brand %}.
{% endblock body %}
