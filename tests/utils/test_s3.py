from django.core.files.storage import default_storage


def default_storage_ls_files(directory=""):
    # List all files in default_storage in a recusrive way
    # Always call without subdirectory
    result = []
    subdirectories, files = default_storage.listdir(directory)
    result += files
    for subdirectory in subdirectories:
        result += [f"{subdirectory}/{file}" for file in default_storage_ls_files(subdirectory)]
    return sorted(result)
