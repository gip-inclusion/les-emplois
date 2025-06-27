from django.core.files.storage import default_storage


def default_storage_ls_files(dirname):
    # `default_storage.listdir`` returns this tuple: ([<list_of_subdirectories>], [<list_of_files>]).
    # Most of the time, we want the file list without the subdirectories.
    return default_storage.listdir(dirname)[-1]
