{% extends "layout/base_email_text_body.md" %}
{% block body %}
Vous avez reçu une demande d’orientation pour le service « {{ orientation.service.name }} ».

Bonjour,

{{ orientation.sender.get_full_name }} de la structure {{ orientation.sender_organization.display_name }} vous a adressé un bénéficiaire pour le service {{ orientation.service.name }}.

Afin de visualiser les détails de la demande et de contacter la personne orientée ou la personne prescriptrice, cliquez sur le lien suivant :
{{ process_link }}

---
Le saviez-vous ?
Le formulaire d’orientation DORA est maintenant intégré à la Plateforme de l’inclusion. Cela permet aux prescripteurs et orienteurs de gérer au même endroit les candidatures en IAE, GEIQ, OPCS, et les orientations vers des services d’insertion.
DORA reste l’annuaire de référence pour toute offre de service d'insertion.
{% endblock body %}
