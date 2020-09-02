from itou.external_data.apis.pe_connect import import_user_data
from itou.utils.actors import REGISTRY


# Decorators are placed in this files because auto-detected by `django_dramatiq_pg`


@REGISTRY.actor()
def async_import_user_data(user_pk, token):
    import_user_data(user_pk, token)
