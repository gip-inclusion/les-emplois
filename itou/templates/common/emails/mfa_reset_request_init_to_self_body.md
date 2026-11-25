{% extends "layout/base_email_text_body.md" %}
{% block body %}

Bonjour {{ user.get_full_name }},

Une demande de réinitialisation de la double authentification (2FA)
vient d’être effectuée pour votre compte {% brand %}. Si
vous êtes à l’origine de cette demande, nous vous invitons à consulter
les informations ci-dessous avant de poursuivre. Dans de nombreux cas,
il est possible de retrouver son accès sans avoir besoin de
réinitialiser la double authentification.

Votre demande a bien été transmise au support technique {% brand "de" %}.
Vous serez notifié par e-mail dès que votre demande aura été traitée.


### Si vous n’êtes pas à l’origine de cette demande

Une demande de réinitialisation que vous n’avez pas effectuée peut
être le signe d’une tentative d’accès à votre compte. Sans attendre,
annulez votre demande par ce lien :

{{ self_cancel_url }}

et contactez notre équipe de sécurité :
[security-mfa@inclusion.gouv.fr](security-mfa@inclusion.gouv.fr).


## Avant de procéder à cette réinitialisation

La plupart des difficultés rencontrées sont liées à une application
d’authentification oubliée, à un code introuvable ou à un changement
de téléphone.


### Avez-vous toujours accès à votre application d’authentification ?

Lors de l’activation de la double authentification, vous avez associé
votre compte à une application qui génère automatiquement un code à 6
chiffres. Ce code n’est pas envoyé par SMS ou par e-mail : il est
généré directement par votre application. Nous vous invitons donc à
vérifier si vous disposez de l’une de ces applications :

- **Sur votre téléphone** : Google Authenticator, Aegis, Microsoft
  Authenticator, Authy, Ente Auth, etc.
- **Sur votre ordinateur** : Un gestionnaire de mots de passe ou une
  application compatible TOTP, comme Proton Authenticator, KeePassXC,
  Bitwarden ou Vaultwarden.

Ouvrez l’application concernée et recherchez l’entrée « {% brand
%} ». Vous devriez y retrouver un code à 6 chiffres qui se renouvelle
toutes les 30 secondes. C’est ce code que vous devez saisir lors de
votre connexion.


### Si vous ne retrouvez pas votre code

Votre code TOTP n’est pas envoyé par e-mail ou par SMS. Pour savoir
comment retrouver votre code, consultez notre
guide :

https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/53055305947537--Double-authentification-je-ne-trouve-pas-mon-code


### Si vous avez perdu votre appareil ou vos codes

Vous avez toujours la possibilité d’accéder à votre compte grâce à
votre code de récupération, si vous l’avez conservé. Nous vous invitons
à suivre la procédure dédiée disponible dans notre centre
d’aide :

https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/49111042350225--Double-authentification-j-ai-perdu-mon-appareil-ou-mes-codes


### Si votre code est expiré ou refusé

Quelques vérifications peuvent être réalisées avant de demander une
réinitialisation. Pour cela, vous pouvez suivre la procédure
dédiée :

https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/53055348322449--Double-authentification-mon-code-est-refus%C3%A9


### Suite de votre demande

Si vous n’avez pas réussi à retrouver votre accès malgré ces
vérifications, votre demande de réinitialisation pourra être traitée
par notre équipe support. Vous serez informé par e-mail de la suite
donnée à votre demande. La double authentification est une protection
essentielle pour sécuriser votre compte et les données auxquelles vous
avez accès. Nous vous remercions de votre vigilance.

L’équipe support {% brand "de" %}.

{% endblock body %}
