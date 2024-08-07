import paramiko
from django.conf import settings


REMOTE_UPLOAD_DIR = "depot"
REMOTE_DOWNLOAD_DIR = "retrait"


def get_sftp_connection() -> paramiko.SFTPClient:
    client = paramiko.SSHClient()
    if settings.ASP_FS_KNOWN_HOSTS:
        client.load_host_keys(settings.ASP_FS_KNOWN_HOSTS)

    client.connect(
        hostname=settings.ASP_FS_SFTP_HOST,
        port=settings.ASP_FS_SFTP_PORT,
        username=settings.ASP_FS_SFTP_USER,
        key_filename=settings.ASP_FS_SFTP_PRIVATE_KEY_PATH,
        disabled_algorithms={
            "pubkeys": ["rsa-sha2-512", "rsa-sha2-256"],  # We want ssh-rsa
        },
        allow_agent=False,  # No need to try other keys if the one we have failed
        look_for_keys=False,  # No need to try other keys if the one we have failed
        timeout=10,
    )
    return client.open_sftp()
