from huey.contrib.djhuey import db_task

from .apis.pe_connect import import_user_data


@db_task()
def import_pe_data(user_pk, token):
    import_user_data(user_pk, token)
