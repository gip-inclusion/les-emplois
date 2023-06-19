import io
import os
import socket
import threading

import paramiko
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from paramiko import ServerInterface


class Server(paramiko.ServerInterface):
    def check_auth_password(self, *args, **kwargs):
        # all are allowed
        return paramiko.AUTH_SUCCESSFUL

    def check_channel_request(self, *args, **kwargs):
        return paramiko.OPEN_SUCCEEDED


class RootedSFTPServer(paramiko.SFTPServerInterface):
    """Taken and adapted from https://github.com/paramiko/paramiko/blob/main/tests/_stub_sftp.py"""

    def __init__(self, server: ServerInterface, *args, root_path, **kwargs):
        self._root_path = root_path
        super().__init__(server, *args, **kwargs)

    def _realpath(self, path):
        return str(self._root_path) + self.canonicalize(path)

    def list_folder(self, path):
        path = self._realpath(path)
        try:
            out = []
            for file_name in os.listdir(path):
                attr = paramiko.SFTPAttributes.from_stat(os.stat(os.path.join(path, file_name)))
                attr.filename = file_name
                out.append(attr)
            return out
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def stat(self, path):
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(self._realpath(path)))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def open(self, path, flags, attr):
        path = self._realpath(path)

        flags = flags | getattr(os, "O_BINARY", 0)
        mode = getattr(attr, "st_mode", None) or 0o777
        try:
            fd = os.open(path, flags, mode)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

        if (flags & os.O_CREAT) and (attr is not None):
            attr._flags &= ~attr.FLAG_PERMISSIONS
            paramiko.SFTPServer.set_file_attr(path, attr)

        if flags & os.O_WRONLY:
            mode_from_flags = "a" if flags & os.O_APPEND else "w"
        elif flags & os.O_RDWR:
            mode_from_flags = "a+" if flags & os.O_APPEND else "r+"
        else:
            mode_from_flags = "r"  # O_RDONLY (== 0)
        try:
            f = os.fdopen(fd, mode_from_flags + "b")
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

        handle = paramiko.SFTPHandle(flags)
        handle.filename = path
        handle.readfile = f
        handle.writefile = f
        return handle

    def remove(self, path):
        try:
            os.remove(self._realpath(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK


@pytest.fixture(scope="session", name="sftp_host_key")
def sftp_host_key_fixture():
    # Use a 1024-bits key otherwise we get an OpenSSLError("digest too big for rsa key")
    return (
        rsa.generate_private_key(key_size=1024, public_exponent=65537)
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )


@pytest.fixture(name="sftp_directory")
def sftp_directory_fixture(tmp_path_factory):
    return tmp_path_factory.mktemp("sftp")


@pytest.fixture(name="sftp_client_factory")
def sftp_client_factory_fixture(sftp_host_key, sftp_directory):
    """
    Set up an in-memory SFTP server thread. Return the client Transport/socket.

    The resulting client Transport (along with all the server components) will
    be the same object throughout the test session; the `sftp_client_factory` fixture then
    creates new higher level client objects wrapped around the client Transport, as necessary.
    """
    # Sockets & transports
    server_socket, client_socket = socket.socketpair()
    server_transport = paramiko.Transport(server_socket)
    client_transport = paramiko.Transport(client_socket)

    # Auth
    server_transport.add_server_key(paramiko.RSAKey.from_private_key(io.StringIO(sftp_host_key)))

    # Server setup
    server_transport.set_subsystem_handler("sftp", paramiko.SFTPServer, RootedSFTPServer, root_path=sftp_directory)
    # The event parameter is here to not block waiting for a client connection
    server_transport.start_server(event=threading.Event(), server=Server())

    client_transport.connect(username="user", password="password")

    def sftp_client_factory(*args, **kwargs):
        return paramiko.SFTPClient.from_transport(client_transport)

    return sftp_client_factory
