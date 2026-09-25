{% extends "layout/base_email_text_body.md" %}
{% load str_filters %}
{% block body %}
Votre demande d’orientation pour {{ orientation.beneficiary.get_full_name|mask_unless:orientation.sender_can_view_personal_information }} a été refusée.

Bonjour,

La structure {{ orientation.service.structure.name }} n’a pas pu donner suite à votre demande d’orientation pour {{ orientation.beneficiary.get_full_name|mask_unless:orientation.sender_can_view_personal_information }} sur le service {{ orientation.service.name }}.

La ou les raisons spécifiques évoquées sont les suivantes :

{% for reason in reasons %}- {{ reason }}
{% endfor %}

{% if orientation.refusal_details %}La structure vous informe également de :
{{ orientation.refusal_details }}{% endif %}

Vous souhaitez faire une nouvelle recherche pour trouver un service adapté au besoin de votre bénéficiaire ? Relancer la recherche :
{{ orientation.new_service_search_url }}
{% endblock body %}
