import enum


class InclusionConnectChannel(str, enum.Enum):
    """This enum is stored in the session, and allow us to change the error message
    in the callback view depending on where the user came from.
    """

    INVITATION = "invitation"
    POLE_EMPLOI = "pole_emploi"
    ACTIVATION = "activation"
    MAP_CONSEILLER = "map_conseiller"
