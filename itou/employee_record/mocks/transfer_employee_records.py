import json
from contextlib import contextmanager

from itou.employee_record.models import EmployeeRecordBatch


_SAMPLE_FILE = "itou/employee_record/mocks/sample_asp_feedback_file.json"

_GOOD_CODE, _GOOD_MSG = "0000", "La ligne de la fiche salarié a été enregistrée avec succès."
_EVIL_CODE, _EVIL_MSG = "6667", "Fiche salarié en erreur"


class SFTPConnectionMock:
    """
    Simple mock for a pysftp / paramiko SFTP Connection object
    """

    # Contains pairs filename->str: content->BytesIO
    FILES = {}

    def __init__(self, *args, **kwargs):
        with open(_SAMPLE_FILE, "rb") as f:
            self.feedback_file_stream = f.read()

        self.FILES = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    def pwd(self):
        return "PWD"

    @contextmanager
    def cd(self, remotepath):
        yield

    def putfo(self, content, remote_path, **kwargs):
        filename = EmployeeRecordBatch.feedback_filename(remote_path)
        self.FILES[filename] = self.process_incoming_file(filename, content)

    def getfo(self, remote_path, stream, **kwargs):
        if content := self.FILES.get(remote_path):
            content.seek(0)
            return stream.write(content.read())

        return stream.write(self.feedback_file_stream)

    def listdir(self):
        print(self.FILES)
        return self.FILES.keys()

    def process_incoming_file(self, filename, content):
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

    def process_incoming_file(self, filename, content):
        batch = json.load(content)
        for employee_record in batch.get("lignesTelechargement", []):
            employee_record["codeTraitement"] = _GOOD_CODE
            employee_record["libelleTraitement"] = _GOOD_MSG
        content.seek(0)
        print(batch)
        json.dump(batch, content)
        content.flush()

        return content


class SFTPConnectionEvil(SFTPConnectionMock):
    pass


class SFTPConnectionChaoticEvil(SFTPConnectionMock):
    pass
