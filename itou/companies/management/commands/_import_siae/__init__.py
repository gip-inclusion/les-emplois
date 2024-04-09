import gzip
import shutil
from pathlib import Path

from py7zr import unpack_7zarchive


def gunzip(archivepath, outdir):
    filename = Path(archivepath).name
    try:
        with gzip.open(archivepath, "rb") as archive:
            with open(Path(outdir) / Path(filename).stem, "wb") as out:
                shutil.copyfileobj(archive, out)
    except gzip.BadGzipFile as e:
        raise shutil.ReadError from e


shutil.register_unpack_format("gz", [".gz"], gunzip)
shutil.register_unpack_format("7zip", [".7z"], unpack_7zarchive)
