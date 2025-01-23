from itou.users.enums import IdentityProvider


def test_identity_provider_configures_allowed_user_kinds():
    for identity_provider in IdentityProvider.values:
        if identity_provider == IdentityProvider.INCLUSION_CONNECT:
            # not used anymore
            continue
        # will raise a KeyError if an implementation is missing for the IdentityProvider
        assert len(IdentityProvider.supported_user_kinds[identity_provider]) > 0
