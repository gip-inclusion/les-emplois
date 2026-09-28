{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour {{ user.first_name|title }},

La structure d’insertion {{ report.company.display_name }} vous envoie un bilan de fin d’accompagnement pour un salarié en fin de contrat de travail que vous accompagnez. Ce bilan a été rempli par {{ report.author.get_full_name }}.

Retrouvez toutes les informations sur l’usager et consultez le bilan en cliquant sur le lien ci-dessous :
{{ report_url }}

Nouveau : les structures d’insertion peuvent désormais remplir un bilan d’accompagnement lorsque le contrat d’un salarié se termine ou vient de se terminer.
{% endblock body %}
