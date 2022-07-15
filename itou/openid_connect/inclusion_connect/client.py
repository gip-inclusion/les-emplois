from ..client import OIDConnectClient, OIDProvider
from . import constants
from .models import InclusionConnectState, InclusionConnectUserData


class inclusionConnectProvider(OIDProvider):
    state_class = InclusionConnectState
    user_data_class = InclusionConnectUserData
    base_url = constants.INCLUSION_CONNECT_REALM_ENDPOINT
    authorize_additional_kwargs = {
        "from": "emplois",  # Display a "Les emplois" logo on the connection page.
    }
    client_id = constants.INCLUSION_CONNECT_CLIENT_ID
    scopes = constants.INCLUSION_CONNECT_SCOPES
    url_namespace = "inclusion_connect"
    session_key: str = constants.INCLUSION_CONNECT_SESSION_KEY


class InclusionConnectClient(OIDConnectClient):
    def __init__(self):
        self.provider = inclusionConnectProvider()


client = InclusionConnectClient()
