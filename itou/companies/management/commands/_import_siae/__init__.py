import gzip
import os
import shutil
from pathlib import Path

import pyzipper


def gunzip(archivepath, outdir):
    filename = Path(archivepath).name
    try:
        with gzip.open(archivepath, "rb") as archive:
            with open(Path(outdir) / Path(filename).stem, "wb") as out:
                shutil.copyfileobj(archive, out)
    except gzip.BadGzipFile as e:
        raise shutil.ReadError from e


def unpack_riae_zip_aes_encrypted(path, directory, **kwargs):
    with pyzipper.AESZipFile(path) as zf:
        zf.extractall(directory, pwd=os.environ["ASP_RIAE_UNZIP_PASSWORD"].encode())


shutil.register_unpack_format("gz", [".gz"], gunzip)
shutil.register_unpack_format("zip-riae", [".riae"], unpack_riae_zip_aes_encrypted)
