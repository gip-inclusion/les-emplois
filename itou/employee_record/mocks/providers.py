from faker.providers import BaseProvider


class INSEECommuneProvider(BaseProvider):
    """
    Provides a random INSEE Commune
    Mainly used for user / job seeker birth place
    """

    __provider__ = "insee_commune"
    __lang__ = "fr_FR"

    codes = [
        "81093",
        "68238",
        "67152",
        "43142",
        "56136",
    ]
