from huey.contrib.djhuey import on_commit_task

from itou.external_data.apis.pe_connect import import_user_pe_data
from itou.utils import triggers


# TODO: drop pe_data_import arg in a future commit
@on_commit_task()
def huey_import_user_pe_data(user, token, pe_data_import=None, triggers_context=None):
    # The triggers_context is provided by the view triggering this task
    with triggers.connection_wrapper():
        import_user_pe_data(user, token, triggers_context)
