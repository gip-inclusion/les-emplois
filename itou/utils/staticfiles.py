import fnmatch
import hashlib
import os
import os.path
import pathlib
import shutil
import tarfile
import zipfile
from urllib.parse import urlparse

import httpx
from django.conf import settings
from django.contrib.staticfiles.finders import BaseFinder


# ITOU_CACHE is used in demo/prod with a sensible XDG compatible default
_CACHE_HOME = os.getenv("ITOU_CACHE", os.getenv("XDG_CACHE_HOME", os.path.join(os.getenv("HOME"), ".cache")))
# Where the downloaded assets (NPM packages, zip files, etc) will be stored
WORKING_DIR = pathlib.Path(_CACHE_HOME) / "itou_cached_assets"
# Where the static assets will be stored for django's FileSystemFinder to find
DESTINATION = settings.STATICFILES_DIRS[0]


# DownloadAndVendorStaticFilesFinder will download & extract/deploy files to
# DESTINATION directory based on the infos defined in ASSET_INFOS
#
# Each ASSET_INFOS entry represents a file to download based on the infos present in
# its `download` entry (mainly `url` & `sha256`, except for the jquery-ui case).
#
# It must also contain either a `target` or `extract` entry to describe the deployment
# process:
# - in the case of a `target` entry, the downloaded file will simply be copied to the
#   `target` value
# - in the case of an `extract` entry, the downloaded file (.zip or .tgz) will be partially
#   extracted based on the infos provided:
#    * `origin` is the base path inside the archive/downloaded file
#    * `destination` is the base path where files will be extracted
#    * `files` is a list of move directives that can either be:
#      - a string filename (that will be found in {origin}/{filename} and extracted to {destination}/{filename})
#      - a tuple (origin_filename, destination_filename) (that will be found in {origin}/{origin_filename} and
#        extracted to {destination}/{destination_filename})
#      - a string glob: all files inside the archive matching the glob {origin}/{glob} will be deployed
#        to a path equal to their path with the {origin} prefix is replaced by {destination}


ASSET_INFOS = {
    "@duetds/date-picker": {
        "download": {
            "url": "https://registry.npmjs.org/@duetds/date-picker/-/date-picker-1.4.0.tgz",
            "sha256": "35bacc775daa4e714c6d6adbaf6084ecbee52e0945d38e86c8e2e105fc7ce49e",
        },
        "extract": {
            "origin": "package",
            "destination": "vendor/duetds-date-picker",
            "files": [
                "LICENSE",
                ("dist/duet/duet-date-picker.system.entry.js", "duet-date-picker.system.entry.js"),
                ("dist/duet/duet.js", "duet.js"),
                ("dist/duet/duet.system.js", "duet.system.js"),
                ("dist/duet/index-7f002a21.system.js", "index-7f002a21.system.js"),
                ("dist/duet/themes/default.css", "themes/default.css"),
            ],
        },
    },
    "bootstrap": {
        "download": {
            "url": "https://github.com/twbs/bootstrap/archive/refs/tags/v5.3.2.zip",
            "sha256": "5542fdffc10ab7590709c5cbb2a5f8c3e33af534db491bb9aab7e8c46573ce8f",
        },
        "extract": {
            "origin": "bootstrap-5.3.2/dist/js",
            "destination": "vendor/bootstrap",
            "files": [
                "bootstrap.min.js",
                "bootstrap.min.js.map",
            ],
        },
    },
    "tiny-slider": {
        "download": {
            "url": "https://github.com/ganlanyuan/tiny-slider/archive/refs/tags/v2.9.4.zip",
            "sha256": "ac906066c097361fd9240ebf7521ee21753ca0740e7b2d31924c8d1ddb91a0ea",
        },
        "extract": {
            "origin": "tiny-slider-2.9.4/dist",
            "destination": "vendor/tiny-slider",
            "files": [
                "min/tiny-slider.js",
                "sourcemaps/tiny-slider.js.map",
            ],
        },
    },
    "htmx.org": {
        "download": {
            "url": "https://registry.npmjs.org/htmx.org/-/htmx.org-1.9.6.tgz",
            "sha256": "061fbce477f32ed1141f69fe449c47c7395725d39e739fe27f7fd5a617d5efe8",
        },
        "extract": {
            "origin": "package",
            "destination": "vendor/htmx",
            "files": [
                "LICENSE",
                ("dist/htmx.min.js", "htmx.min.js"),
                ("dist/ext/debug.js", "ext/debug.js"),
                ("dist/ext/event-header.js", "ext/event-header.js"),
            ],
        },
    },
    "iframe-resizer": {
        "download": {
            "url": "https://registry.npmjs.org/iframe-resizer/-/iframe-resizer-4.3.2.tgz",
            "sha256": "3dfa6c0986ba0ad5f74d0724480cc71620420f2658be5a17e586ee4ab988335e",
        },
        "extract": {
            "origin": "package",
            "destination": "vendor/iframe-resizer",
            "files": [
                "LICENSE",
                ("js/iframeResizer.contentWindow.map", "iframeResizer.contentWindow.map"),
                ("js/iframeResizer.contentWindow.min.js", "iframeResizer.contentWindow.min.js"),
            ],
        },
    },
    "jquery": {
        "download": {
            "url": "https://registry.npmjs.org/jquery/-/jquery-3.7.1.tgz",
            "sha256": "68a9f787516da47c680e09c187bcbac4536b6f85d90eb882844e12919e583f53",
        },
        "extract": {
            "origin": "package",
            "destination": "vendor/jquery",
            "files": [
                "LICENSE.txt",
                ("dist/jquery.min.js", "jquery.min.js"),
            ],
        },
    },
    "ol": {
        "download": {
            "url": "https://registry.npmjs.org/ol/-/ol-7.2.2.tgz",
            "sha256": "08a92332623609281091f187da1fd3b7c2d2c8509a9619d1603e6b58bdf9146d",
        },
        "extract": {
            "origin": "package",
            "destination": "vendor/ol",
            "files": [
                "LICENSE.md",
                "ol.css",
                ("dist/ol.js", "ol.js"),
                ("dist/ol.js.map", "ol.js.map"),
            ],
        },
    },
    "popper.js": {
        "download": {
            "url": "https://registry.npmjs.org/@popperjs/core/-/core-2.11.8.tgz",
            "sha256": "8e09bdfa912035668e62cea61321bce27cbd011b85672055db25d271bd63af49",
        },
        "extract": {
            "origin": "package/dist/umd",
            "destination": "vendor/bootstrap",
            "files": [
                "popper.min.js",
                "popper.min.js.map",
            ],
        },
    },
    "redoc": {
        "download": {
            "url": "https://cdn.redoc.ly/redoc/v2.0.0/bundles/redoc.standalone.js",
            "sha256": "c7f107f5259486ec29f726db25e31a46a563b09f5209fd90c0371677e576d311",
        },
        "target": "vendor/redoc/redoc.standalone.js",
    },
    "redoc/map": {
        "download": {
            "url": "https://cdn.redoc.ly/redoc/v2.0.0/bundles/redoc.standalone.js.map",
            "sha256": "ae54c013193df71fe0a18ddddf20e8893b1c0c80b4a3ddcd8a969dae03fdf198",
        },
        "target": "vendor/redoc/redoc.standalone.js.map",
    },
    "redoc/LICENSE": {
        "download": {
            "url": "https://cdn.redoc.ly/redoc/v2.0.0/bundles/redoc.standalone.js.LICENSE.txt",
            "sha256": "d346d7ec025844f5f7df51887302bb105782b8199eb9b382d9133435e348b9b2",
        },
        "target": "vendor/redoc/redoc.standalone.js.LICENSE.txt",
    },
    "tarteaucitronjs": {
        "download": {
            "url": "https://registry.npmjs.org/tarteaucitronjs/-/tarteaucitronjs-1.14.0.tgz",
            "sha256": "e7d635b081b165d297809e3e86077c4219b022105e3a0a6a25e3c1f9657a2231",
        },
        "extract": {
            "origin": "package",
            "destination": "vendor/tarteaucitron",
            "files": [
                "LICENSE",
                "tarteaucitron.js",
                "tarteaucitron.services.js",
                "lang/tarteaucitron.en.js",
                "lang/tarteaucitron.fr.js",
            ],
        },
    },
    "theme-inclusion": {
        "download": {
            "url": "https://github.com/gip-inclusion/itou-theme/archive/refs/tags/v1.7.0.zip",
            "sha256": "252e74f43128bd6c69348321b4dca8a8767cbace14e4c087f14738496a5b6f4c",
        },
        "extract": {
            "origin": "itou-theme-1.7.0/dist",
            "destination": "vendor/theme-inclusion/",
            "files": [
                "javascripts/app.js",
                "stylesheets/app.css",
                "fonts/marianne/*",
                "fonts/remixicon/*",
                "fonts/coveredbyyourgrace/*",
                "files/*",
                "images/*",
                "images/metabase/*",
            ],
        },
    },
}


def download(asset_key, download_infos):
    prefix = f"Updating {asset_key}"
    file_to_download = download_infos["url"]
    filename = download_infos.get("filename", os.path.basename(urlparse(file_to_download).path))
    filepath = WORKING_DIR / filename
    expected_hash_value = download_infos["sha256"]
    if filepath.exists():
        if expected_hash_value is not None:
            hash_value = hashlib.sha256(filepath.read_bytes()).hexdigest()
            if hash_value != expected_hash_value:
                print(
                    f"{prefix} - {filepath} found - hash {hash_value} KO (expected: {expected_hash_value}) - deleting"
                )
                filepath.unlink()
        else:
            print(f"{prefix} - {filepath} found - no hash verification - keeping file")

    if not filepath.exists():
        filepath.parent.mkdir(parents=True, exist_ok=True)
        print(f"{prefix} - Downloading {filepath}")

        hash_value = hashlib.sha256()
        with (
            httpx.stream(method="GET", follow_redirects=True, url=download_infos["url"]) as response,
            open(filepath, "wb") as f,
        ):
            for data in response.iter_bytes():
                f.write(data)
                hash_value.update(data)
        hash_value = hash_value.hexdigest()
        print(f"{prefix} - Hash value for downloaded file: {hash_value}")
        if expected_hash_value is not None and hash_value != expected_hash_value:
            raise ValueError(f"Downloaded {filepath} - hash {hash_value} KO (expected: {expected_hash_value})")
    return filepath


def compute_moves(existing_filenames, extract_infos):
    origin = extract_infos["origin"].removesuffix("/")
    destination = os.path.join(DESTINATION, extract_infos["destination"]).removesuffix("/")
    moves = []
    files_to_extract = set()
    globs_to_extract = set()
    for name in extract_infos["files"]:
        if isinstance(name, tuple | list):
            name, new_name = name
        else:
            new_name = name
        origin_name = f"{origin}/{name}"
        if "*" in name:
            globs_to_extract.add(origin_name)
        else:
            files_to_extract.add(origin_name)
            moves.append((origin_name, f"{destination}/{new_name}"))

    if unfound := set(files_to_extract) - set(existing_filenames):
        raise ValueError(f"Some files could not be found: {unfound}")
    for glob in globs_to_extract:
        glob_files = fnmatch.filter(existing_filenames, glob)
        if not glob_files:
            raise ValueError(f"No files found matching {glob}")
        for filepath in glob_files:
            if filepath[-1] == "/":
                # We don't want the directories matching the globs
                continue
            # Replace origin prefix by destination
            destination_filepath = f"{destination}{filepath[len(origin):]}"
            moves.append((filepath, destination_filepath))

    return moves


def move(filepath: pathlib.Path, target):
    file_destination = os.path.join(DESTINATION, target)
    os.makedirs(os.path.dirname(file_destination), exist_ok=True)
    shutil.copy(filepath, file_destination)


def extract(filepath: pathlib.Path, extract_infos):
    if filepath.suffix == ".zip":
        with zipfile.ZipFile(filepath) as z:
            for file_origin, file_destination in compute_moves(z.namelist(), extract_infos):
                os.makedirs(os.path.dirname(file_destination), exist_ok=True)
                with open(file_destination, "wb") as f:
                    f.write(z.read(file_origin))
    elif filepath.suffix == ".tgz":
        with tarfile.open(filepath) as t:
            for file_origin, file_destination in compute_moves(t.getnames(), extract_infos):
                os.makedirs(os.path.dirname(file_destination), exist_ok=True)
                with open(file_destination, "wb") as f:
                    f.write(t.extractfile(file_origin).read())
    else:
        raise ValueError(f"Unsupported suffix for {filepath}")


def update(asset_key):
    asset_info = ASSET_INFOS[asset_key]
    path = download(asset_key, asset_info["download"])
    # Either target or extract_infos
    if target := asset_info.get("target"):
        assert not asset_info.get("extract")
        move(path, target)
    else:
        assert not asset_info.get("target")
        extract(path, asset_info["extract"])


def update_all():
    for asset_key in ASSET_INFOS:
        update(asset_key)


class DownloadAndVendorStaticFilesFinder(BaseFinder):
    def check(self, **kwargs):
        # Nothing to configure, so nothing to check
        return []

    def list(self, ignore_patterns):
        # This finder finds & lists nothing but puts the files in STATICFILES_DIRS[0]
        # for django.contrib.staticfiles.finders.FileSystemFinder to find
        update_all()
        return []

    def find(self, path, all=False):
        return []
