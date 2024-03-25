from django.core import mail

from itou.companies.enums import CompanyKind


def assert_set_admin_role__creation(user, organization):
    # New admin.
    assert user in organization.active_admin_members

    # The admin should receive a valid email
    [email] = mail.outbox
    assert "Votre rôle d’administrateur" == email.subject
    assert (
        "Vous avez désormais le statut d’administrateur sur l’espace professionnel de "
        f"votre organisation {organization.name} ({organization.kind})"
    ) in email.body
    assert email.to[0] == user.email

    if user.is_prescriber:
        assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/14737265161617" in email.body
    elif user.is_labor_inspector:
        assert "https://aide.emplois.inclusion.beta.gouv.fr/" not in email.body
    elif user.is_employer:
        if organization.kind in [CompanyKind.ACI, CompanyKind.AI, CompanyKind.EI, CompanyKind.ETTI, CompanyKind.EITI]:
            assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/14738355467409" in email.body
        elif organization.kind in [CompanyKind.EA, CompanyKind.OPCS]:
            assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/articles/16925381169681" in email.body
        elif organization.kind == CompanyKind.GEIQ:
            assert "https://aide.emplois.inclusion.beta.gouv.fr/hc/fr/categories/15209741332113" in email.body
        else:
            raise AssertionError("Invalid siae kind")
    else:
        raise AssertionError("Invalid user kind")


def assert_set_admin_role__removal(user, organization):
    # Admin removal.
    assert user not in organization.active_admin_members

    # The admin should receive a valid email
    [email] = mail.outbox
    assert f"[Désactivation] Vous n'êtes plus administrateur de {organization.display_name}" == email.subject
    assert "Un administrateur vous a retiré les droits d'administrateur d'une structure" in email.body
    assert email.to[0] == user.email
