from huey.contrib.djhuey import db_task

from .apis.pe_connect import import_user_pe_data


@db_task()
def huey_import_user_pe_data(user, token, pe_data_import):
    import_user_pe_data(user, token, pe_data_import)
