{% extends "layout/base_email_text_body.md" %}
{% block body %}
Bonjour,

Une fiche salarié est revenue en erreur 3437 : {{ employee_record_url }} et son traitement automatique a échoué
car un compte usager doublon a été détecté.

L’usager lié à la fiche salarié (avec un ID itou inconnu de l’ASP) est le [{{ employee_record_job_seeker_id }}]({{ employee_record_job_seeker_url}}).

L’usager avec l’ID itou renvoyé par l’ASP est le [{{ duplicate_job_seeker_id }}]({{ duplicate_job_seeker_url }}).

Cordialement,
{% endblock body %}
