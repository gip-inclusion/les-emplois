import json
from contextlib import contextmanager

from itou.employee_record.models import EmployeeRecordBatch


_SAMPLE_FILE = "itou/employee_record/mocks/sample_asp_feedback_file.json"
_GOOD_CODE, _GOOD_MSG = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
_EVIL_CODE, _EVIL_MSG = "6667", "Fiche salarié en erreur"
_FILES = {}


class SFTPConnectionMock:
    """
    Simple mock for a pysftp / paramiko SFTP Connection object
    """

    # Contains pairs filename->str: content->BytesIO

    def __init__(self, *args, **kwargs):
        with open(_SAMPLE_FILE, "rb") as f:
            self.feedback_file_stream = f.read()

        self.FILES = {}

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc_val, _exc_tb):
        pass

    @property
    def pwd(self):
        return "PWD"

    @contextmanager
    def cd(self, _remotepath):
        yield

    def putfo(self, content, remote_path, **kwargs):
        filename = EmployeeRecordBatch.feedback_filename(remote_path)
        _FILES[filename] = self.process_incoming_file(filename, content)

    def getfo(self, remote_path, stream, **kwargs):
        if content := self.FILES.get(remote_path):
            content.seek(0)
            return stream.write(content.read())

        return stream.write(self.feedback_file_stream)

    def listdir(self):
        return _FILES.keys()

    def process_incoming_file(self, _filename, content):
        """
        By default, does nothing
        Store incoming file "as-is"
        """
        return content


# Custom SFTP "connection" mocks


class SFTPGoodConnectionMock(SFTPConnectionMock):
    """
    When sending (--upload) an employee record batch file via this connection
    getting it back (--download) will render a file with all employee records validated
    """

    def getfo(self, remote_path, stream, **kwargs):
        if content := _FILES.get(remote_path):
            content.seek(0)
            batch = json.load(content)

            for employee_record in batch.get("lignesTelechargement", []):
                employee_record["codeTraitement"] = _GOOD_CODE
                employee_record["libelleTraitement"] = _GOOD_MSG

            return stream.write(json.dumps(batch).encode())

        return stream


class SFTPConnectionEvil(SFTPConnectionMock):
    pass


class SFTPConnectionChaoticEvil(SFTPConnectionMock):
    pass
