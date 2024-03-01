from django.core import mail


def assert_set_admin_role__creation(user, organization):
    # New admin.
    assert user in organization.active_admin_members

    # The admin should receive a valid email
    [email] = mail.outbox
    assert f"[Activation] Vous êtes désormais administrateur de {organization.display_name}" == email.subject
    assert "Vous êtes administrateur d'une structure sur les emplois de l'inclusion" in email.body
    assert email.to[0] == user.email


def assert_set_admin_role__removal(user, organization):
    # Admin removal.
    assert user not in organization.active_admin_members

    # The admin should receive a valid email
    [email] = mail.outbox
    assert f"[Désactivation] Vous n'êtes plus administrateur de {organization.display_name}" == email.subject
    assert "Un administrateur vous a retiré les droits d'administrateur d'une structure" in email.body
    assert email.to[0] == user.email
