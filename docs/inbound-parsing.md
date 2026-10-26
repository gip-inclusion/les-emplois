# Inbound parsing

## Contexte

L’*inbound parsing* (analyse de mails entrants) est une technique qui permet de
traiter des mails adressés à un domaine en particulier, d’en extraire
automatiquement le contenu et en-têtes pour en faire ce qu’on veut ensuite.

Le besoin de recourir à l’*inbound parsing* est arrivé dans le cadre des
orientations vers des services d’insertion (application `itou.insertion`).
On suppose qu’une partie des demandes d’orientations se fait sur un autre canal
que notre formulaire d’orientation, par mail ou téléphone.
Pour mesurer l’utilisation du canal mail, on veut suivre au moins le début des
échanges entre un prescripteur et un offreur de services.


## Mise en place

### Brevo

- le domaine `reply.inclusion.gouv.fr` a été ajouté à
  [la liste](https://app.brevo.com/senders/domain/list) des domaines gérés par
  Brevo
- les entrées DNS MX, DKIM, DMARC ont été créées dans [le dépôt
  infrastructure](https://github.com/gip-inclusion/infrastructure/)
- un *webhook* a été créé via l’API Brevo :
  ```
  curl --request POST -H "api-key: <personal_token>" https://api.brevo.com/v3/webhooks -d '{
    "type": "inbound",
    "events": ["inboundEmailProcessed"],
    "url":"https://plateforme.inclusion.gouv.fr/api/v1/inbound-parsing/reply-webhook",
    "domain": "reply.inclusion.gouv.fr",
    "description": "Webhook triggered by inbound emails", "auth": {"token": "<BrevoToken>"}
  }'
  ```
  où `personal_token` est le jeton personnel pour l’API de Brevo et `BrevoToken`
  le jeton créé sur la plateforme (modèle `itou.api.models.BrevoToken`)


### Plateforme

- un jeton `BrevoToken` a été généré
- la variable `INBOUND_PARSING_SUBDOMAIN` a été définie à
  `reply.inclusion.gouv.fr`

### Démo

Le même mécanisme a été mis en place en démo avec le sous-domaine `demo.reply.inclusion.gouv.fr`.


## Fonctionnement

Tous les emails envoyés à `*@reply.inclusion.gouv.fr` sont reçus par Brevo.
À chaque email reçu, Brevo effectue une requête `POST` avec un [payload
défini](https://developers.brevo.com/docs/inbound-parse-webhooks#parsed-email-payload)
à une route API de la plateforme qui réalise le traitement.

Les détails de l’implémentation se trouvent dans `itou.api.inbound_parsing`.

L’API Brevo permet de lister les événements relatifs à un email, tel que :

```
curl -H "api-key: <personal_token>" https://api.brevo.com/v3/inbound/events/c9f38564-2779-488d-b4a3-9986cdae9c42

{
  "receivedAt": "2026-10-19T17:41:45.000+02:00",
  "deliveredAt": "2026-10-19T17:42:21.000+02:00",
  "messageId": "<cc61f6dd-1434-4676-9293-3d32589a0ba2@inclusion.gouv.fr>",
  "sender": "sender@domain.tld",
  "recipient": "w2kyl657thcenl1dmll7_sa@reply.inclusion.gouv.fr",
  "subject": "Re: Laura MORANS de la structure Vertigo Films souhaite vous adresser un usager",
  "attachments": [],
  "logs": [
    {
      "date": "2026-10-19T17:41:45.000+02:00",
      "type": "received"
    },
    {
      "date": "2026-10-19T17:41:49.000+02:00",
      "type": "processed"
    },
    {
      "date": "2026-10-19T17:42:21.000+02:00",
      "type": "webhookDelivered"
    }
  ]
}
```

### Que se passe-t-il en cas d’indisponibilité de la plateforme ?

Si le webhook Brevo tente d’envoyer une requête à la plateforme, mais que
celle-ci est indisponible, alors Brevo réessaie jusqu’à 4 fois :

1. 10 minutes plus tard
2. 1 heure plus tard
3. 2 heures plus tard
4. 8 heures plus tard

([source](https://developers.brevo.com/docs/retry-mechanism))


### Que se passe-t-il en cas d’erreur du côté de la plateforme (codes 4xx, 5xx) ?

Brevo ne réessaie pas de contacter la plateforme.
Une erreur nous parvient via Sentry.

([source](https://developers.brevo.com/docs/retry-mechanism))


## Les choses qui ne fonctionnent pas

### Un `reply-to` dans un lien `mailto:`

La [RFC 6068](https://www.rfc-editor.org/info/rfc6068/#section-4) dit :

    The creator of a 'mailto' URI cannot expect the resolver of a URI to
    understand more than the "subject" header field and "body".  Clients
    that resolve 'mailto' URIs into mail messages MUST be able to
    correctly create [RFC5322]-compliant mail messages using the
    "subject" header field and "body".

### Plusieurs `reply-to` dans un mail envoyé par Mailjet ou Brevo

L’API v3.1 de Mailjet ne permet pas de renseigner plusieurs adresses dans le
`ReplyTo`.
De plus, les en-têtes personnalisées ne sont pas prises en compte s’il existe
une propriété dédiée
([source](https://dev.mailjet.com/docs/email-api/send-api-v31/add-email-headers)).
C’est le cas du `ReplyTo`.

Les mêmes limitations existent pour Brevo
([source](https://developers.brevo.com/docs/smtp-integration#reply-to-object:~:text=Only%20non%2Dstandard%20headers%20are%20supported)).

Anymail (le paquet Python/Django faisant l’interface entre notre backend et
Mailjet ou Brevo) précise également cela :
- [Mailjet](https://anymail.dev/en/stable/esps/mailjet/#limitations-and-quirks)
- [Brevo](https://anymail.dev/en/stable/esps/brevo/#limitations-and-quirks)
