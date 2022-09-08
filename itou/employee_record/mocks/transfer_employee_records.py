import json
import random
from contextlib import contextmanager

from itou.employee_record.models import EmployeeRecord, EmployeeRecordBatch


SUCCESS_MSG = "La ligne de la fiche salarié a été enregistrée avec succès."
ERROR_CODE, ERROR_MSG = "6667", "Fiche salarié en erreur"
FILES = {}


class SFTPConnectionMock:
    """
    Simple mock for a pysftp / paramiko SFTP Connection object
    """

    # Contains pairs filename->str: content->BytesIO

    def __init__(self, *args, **kwargs):
        self.feedback_file_stream = None

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
        FILES[filename] = self.process_incoming_file(filename, content)

    def getfo(self, remote_path, stream, **kwargs):
        if content := FILES.get(remote_path):
            content.seek(0)
            return stream.write(content.read())

        return stream.write(self.feedback_file_stream)

    def listdir(self):
        return FILES.keys()

    def remove(self, path):
        if FILES.get(path):
            del FILES[path]

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
        if content := FILES.get(remote_path):
            content.seek(0)
            batch = json.load(content)

            for employee_record in batch.get("lignesTelechargement", []):
                employee_record["codeTraitement"] = EmployeeRecord.ASP_PROCESSING_SUCCESS_CODE
                employee_record["libelleTraitement"] = SUCCESS_MSG

            return stream.write(json.dumps(batch).encode())

        return stream


class SFTPAllDupsConnectionMock(SFTPConnectionMock):
    """Same as good connection mock, but returns only employee records with 3436 processing code."""

    def getfo(self, remote_path, stream, **kwargs):
        if content := FILES.get(remote_path):
            content.seek(0)
            batch = json.load(content)

            for employee_record in batch.get("lignesTelechargement", []):
                employee_record["codeTraitement"] = EmployeeRecord.ASP_DUPLICATE_ERROR_CODE
                employee_record["libelleTraitement"] = ERROR_MSG

            return stream.write(json.dumps(batch).encode())

        return stream


class SFTPEvilConnectionMock(SFTPGoodConnectionMock):
    """
    Behaves just like a good connection,
    except that at one random point,
    the connection will fail...
    """

    will_crash = random.randint(1, 6)

    @property
    def pwd(self):
        if self.will_crash == 1:
            raise Exception("SFTP/PWD did crash!")
        super.pwd()

    @contextmanager
    def cd(self, remotepath):
        if self.will_crash == 2:
            raise Exception("SFTP/CD did crash!")
        super.cd(remotepath)

    def putfo(self, content, remote_path, **kwargs):
        if self.will_crash == 3:
            raise Exception("SFTP/CD did crash!")
        super.putfo(content, remote_path, **kwargs)

    def getfo(self, remote_path, stream, **kwargs):
        if self.will_crash == 4:
            raise Exception("SFTP/GETFO did crash!")
        super.getfo(remote_path, stream, **kwargs)

    def listdir(self):
        if self.will_crash == 5:
            raise Exception("SFTP/LISTDIR did crash!")
        super.listdir()

    def process_incoming_file(self, filename, content):
        if self.will_crash == 6:
            raise Exception("procesing_file did crash!")
        super.process_incoming_file(filename, content)


class SFTPBadConnectionMock(SFTPGoodConnectionMock):
    """
    Always fail (as soon as we CD somewhere on the server)
    """

    @contextmanager
    def cd(self, remotepath):
        raise Exception("SFTP/CD did crash!")
