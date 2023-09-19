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


_CACHE_HOME = os.getenv("XDG_CACHE_HOME", os.path.join(os.getenv("HOME"), ".cache"))
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
            "origin": "package/dist/duet",
            "destination": "vendor/duetds-date-picker",
            "files": [
                "duet-date-picker.system.entry.js",
                "duet.js",
                "duet.system.js",
                "index-7f002a21.system.js",
                "themes/default.css",
            ],
        },
    },
    "bootstrap": {
        "download": {
            "url": "https://github.com/twbs/bootstrap/releases/download/v4.6.2/bootstrap-4.6.2-dist.zip",
            "sha256": "dc9b29fe7100e69d1a512860497bd2237eadccde6e813e588416429359832dce",
        },
        "extract": {
            "origin": "bootstrap-4.6.2-dist/js",
            "destination": "vendor/bootstrap",
            "files": [
                "bootstrap.js",
                "bootstrap.js.map",
                "bootstrap.min.js",
                "bootstrap.min.js.map",
            ],
        },
    },
    "dropzone": {
        "download": {
            "url": "https://registry.npmjs.org/dropzone/-/dropzone-5.9.2.tgz",
            "sha256": "3f5a46d160faec41c834f00379444fe172b5b7793c3a4230307941728bd1a8f1",
        },
        "extract": {
            "origin": "package/dist/min",
            "destination": "vendor/dropzone",
            "files": [
                "dropzone.min.css",
                "dropzone.min.js",
            ],
        },
    },
    "htmx.org": {
        "download": {
            "url": "https://registry.npmjs.org/htmx.org/-/htmx.org-1.8.2.tgz",
            "sha256": "e0e10e29d3033d98c15ad25d90608685a61b20e1d813f8b9c3c2e00b9055d525",
        },
        "extract": {
            "origin": "package/dist",
            "destination": "vendor/htmx",
            "files": [
                "htmx.min.js",
                "ext/*",
            ],
        },
    },
    "iframe-resizer": {
        "download": {
            "url": "https://registry.npmjs.org/iframe-resizer/-/iframe-resizer-4.3.2.tgz",
            "sha256": "3dfa6c0986ba0ad5f74d0724480cc71620420f2658be5a17e586ee4ab988335e",
        },
        "extract": {
            "origin": "package/js",
            "destination": "vendor/iframe-resizer",
            "files": [
                "iframeResizer.contentWindow.map",
                "iframeResizer.contentWindow.min.js",
            ],
        },
    },
    "jquery": {
        "download": {
            "url": "https://registry.npmjs.org/jquery/-/jquery-3.6.1.tgz",
            "sha256": "06be03afa548debcfef4f5773b044ed2a9ace7541b4d422a8c28cbb3498e900f",
        },
        "extract": {
            "origin": "package/dist",
            "destination": "vendor/jquery",
            "files": [
                "jquery.min.js",
            ],
        },
    },
    "jquery-ui": {
        "download": {
            "url": "https://download.jqueryui.com/download",
            "sha256": None,  # The file is regenerated for each request making its hash unpredictable
            # Update filename each time an option is changed to invalidate the cache
            # (since no hash is provided)
            "filename": "jquery-ui-1.13.2.custom.zip",
            "post": {
                "version": "1.13.2",
                "widget": "on",
                "position": "on",
                "jquery-patch": "on",
                "keycode": "on",
                "unique-id": "on",
                "widgets/autocomplete": "on",
                "widgets/menu": "on",
                "theme": "ffDefault=Arial%2CHelvetica%2Csans-serif&fsDefault=1em&fwDefault=normal&cornerRadius=3px&bgColorHeader=e9e9e9&bgTextureHeader=flat&borderColorHeader=dddddd&fcHeader=333333&iconColorHeader=444444&bgColorContent=ffffff&bgTextureContent=flat&borderColorContent=dddddd&fcContent=333333&iconColorContent=444444&bgColorDefault=f6f6f6&bgTextureDefault=flat&borderColorDefault=c5c5c5&fcDefault=454545&iconColorDefault=777777&bgColorHover=ededed&bgTextureHover=flat&borderColorHover=cccccc&fcHover=2b2b2b&iconColorHover=555555&bgColorActive=007fff&bgTextureActive=flat&borderColorActive=003eff&fcActive=ffffff&iconColorActive=ffffff&bgColorHighlight=fffa90&bgTextureHighlight=flat&borderColorHighlight=dad55e&fcHighlight=777620&iconColorHighlight=777620&bgColorError=fddfdf&bgTextureError=flat&borderColorError=f1a899&fcError=5f3f3f&iconColorError=cc0000&bgColorOverlay=aaaaaa&bgTextureOverlay=flat&bgImgOpacityOverlay=0&opacityOverlay=30&bgColorShadow=666666&bgTextureShadow=flat&bgImgOpacityShadow=0&opacityShadow=30&thicknessShadow=5px&offsetTopShadow=0px&offsetLeftShadow=0px&cornerRadiusShadow=8px",  # noqa
                "theme-folder-name": "base",
                "scope": "",
            },
        },
        "extract": {
            "origin": "jquery-ui-1.13.2.custom",
            "destination": "vendor/jquery-ui",
            "files": [
                "jquery-ui.css",
                "jquery-ui.js",
                "jquery-ui.min.css",
                "jquery-ui.min.js",
                "images/*",
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
                "ol.css",
                ("dist/ol.js", "ol.js"),
                ("dist/ol.js.map", "ol.js.map"),
            ],
        },
    },
    "popper.js": {
        "download": {
            "url": "https://registry.npmjs.org/popper.js/-/popper.js-1.16.1.tgz",
            "sha256": "756d507afd865981073a5b3c204239196c33f87b39a7c5c65d5e2ecac1d73271",
        },
        "extract": {
            "origin": "package/dist/umd",
            "destination": "vendor/bootstrap",
            "files": [
                "popper.js",
                "popper.js.map",
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
    "tarteaucitronjs": {
        "download": {
            "url": "https://registry.npmjs.org/tarteaucitronjs/-/tarteaucitronjs-1.11.0.tgz",
            "sha256": "b5110111677f8974e4f136a15bed3b435813a700b0f4d39c9036c5e40d376d7f",
        },
        "extract": {
            "origin": "package",
            "destination": "vendor/tarteaucitron",
            "files": [
                "tarteaucitron.js",
                "tarteaucitron.services.js",
                "lang/tarteaucitron.en.js",
                "lang/tarteaucitron.fr.js",
            ],
        },
    },
    "theme-inclusion": {
        "download": {
            "url": "https://github.com/gip-inclusion/itou-theme-bs4/archive/refs/tags/v0.7.5.zip",
            "sha256": "a7f42bf9b2efd9c1369bd7602f4bb2e81dc5711216061a99c20277d4b96f3115",
        },
        "extract": {
            "origin": "itou-theme-bs4-0.7.5/dist",
            "destination": "vendor/theme-inclusion/",
            "files": [
                "javascripts/app.js",
                "stylesheets/app.css",
                "fonts/marianne/*",
                "fonts/remixicon/*",
                "images/*",
                "images/metabase/*",
            ],
        },
    },
}


def download(download_infos):
    file_to_download = download_infos["url"]
    filename = download_infos.get("filename", os.path.basename(urlparse(file_to_download).path))
    filepath = WORKING_DIR / filename
    expected_hash_value = download_infos["sha256"]
    if filepath.exists():
        if expected_hash_value is not None:
            hash_value = hashlib.sha256(filepath.read_bytes()).hexdigest()
            if hash_value != expected_hash_value:
                print(f"{filepath} found - hash {hash_value} KO (expected: {expected_hash_value}) - deleting")
                filepath.unlink()
            else:
                print(f"{filepath} found - hash OK")
        else:
            print(f"{filepath} found - no hash verification - keeping file")

    if not filepath.exists():
        filepath.parent.mkdir(exist_ok=True)
        print(f"Downloading {filepath}")

        stream_kwargs = {
            "url": download_infos["url"],
        }
        if post_data := download_infos.get("post"):
            stream_kwargs.update({"method": "POST", "data": post_data, "timeout": 10})
        else:
            stream_kwargs.update({"method": "GET", "follow_redirects": True})
        hash_value = hashlib.sha256()
        with httpx.stream(**stream_kwargs) as response, open(filepath, "wb") as f:
            for data in response.iter_bytes():
                f.write(data)
                hash_value.update(data)
        hash_value = hash_value.hexdigest()
        print(f"Hash value for downloaded file: {hash_value}")
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
        if isinstance(name, (tuple, list)):
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
    print(f"Updating {asset_key}")
    asset_info = ASSET_INFOS[asset_key]
    path = download(asset_info["download"])
    # Either target or extract_infos
    if target := asset_info.get("target"):
        move(path, target)
        assert not asset_info.get("extract")
    else:
        extract(path, asset_info["extract"])
        assert not asset_info.get("target")


def update_all():
    print(f"Using cache directory: {WORKING_DIR}")
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
