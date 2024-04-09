import gzip
import shutil
from pathlib import Path


def gunzip(archivepath, outdir):
    filename = Path(archivepath).name
    try:
        with gzip.open(archivepath, "rb") as archive:
            with open(Path(outdir) / Path(filename).stem, "wb") as out:
                shutil.copyfileobj(archive, out)
    except gzip.BadGzipFile as e:
        raise shutil.ReadError from e


shutil.register_unpack_format("gz", [".gz"], gunzip)
