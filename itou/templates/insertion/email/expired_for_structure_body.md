{% extends "layout/base_email_text_body.md" %}
{% block body %}
La demande d’orientation pour {{ orientation.beneficiary.get_full_name }} a expiré.

Bonjour,

{{ orientation.sender.get_full_name }} de la structure {{ orientation.sender_organization.display_name }} vous a adressé un bénéficiaire pour le service {{ orientation.service.name }}, le {{ orientation.created_at|date:"d/m/Y" }}.

N’ayant pas reçu de réponses de votre de part dans le délai limite de {{ orientation.PENDING_EXPIRATION_PERIOD_DAYS }} jours, cette demande a été automatiquement annulée.

Nous vous remercions pour votre engagement.

Accéder à la demande :
{{ process_link }}

---
Le saviez-vous ?
Le formulaire d’orientation DORA est maintenant intégré à la Plateforme de l’inclusion. Cela permet aux prescripteurs et orienteurs de gérer au même endroit les candidatures en IAE, GEIQ, OPCS, et les orientations vers des services d’insertion.
DORA reste l’annuaire de référence pour toute offre de service d'insertion.
{% endblock body %}
