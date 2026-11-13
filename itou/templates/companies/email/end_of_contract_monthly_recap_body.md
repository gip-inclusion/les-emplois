{% extends "layout/base_email_text_body.md" %}
{% load str_filters %}
{% block body %}
Bonjour {{ user.first_name|title }},

{{ contracts|length|pluralizefr:"Voici le salarié,Voici les salariés" }} que vous accompagnez chez {{ structure.display_name }} dont le contrat se termine ce mois-ci ou s’est terminé le mois dernier sans suite connue.

{{ contracts|length|pluralizefr:"Remplir son bilan d’accompagnement permet à son prescripteur de préparer la suite avec lui.,Remplir leur bilan d’accompagnement permet à leur prescripteur de préparer la suite avec eux." }}

Pensez aussi à déclarer à l’ASP les sorties et les renouvellements de contrat dès que possible. Si vous avez prévu de renouveler un salarié, vous pouvez l’ignorer dans cette liste.
{% if last_month_contract_lines %}

**{{ last_month_contracts_count|pluralizefr:"Contrat terminé,Contrats terminés" }} le mois dernier ({{ last_month_contracts_count }})**
{% for line in last_month_contract_lines %}
- [{{ line.contract.job_seeker.get_full_name }}]({{ line.job_seeker_url }}) – fin le {{ line.contract.end_date|date:"d/m/Y" }} – Remplir le bilan : {{ line.pro_support_report_url }}{% endfor %}
{% endif %}
{% if this_month_contract_lines %}

**{{ this_month_contracts_count|pluralizefr:"Contrat qui se termine,Contrats qui se terminent" }} ce mois-ci ({{ this_month_contracts_count }})**
{% for line in this_month_contract_lines %}
- [{{ line.contract.job_seeker.get_full_name }}]({{ line.job_seeker_url }}) – fin{% if not line.contract.has_ended %} prévue{% endif %} le {{ line.contract.end_date|date:"d/m/Y" }} – Remplir le bilan : {{ line.pro_support_report_url }}{% endfor %}
{% endif %}

Voir toute la liste : {{ end_of_journey_list_url }}

{% include "companies/email/end_of_journey_footer.md" %}
{% endblock body %}
