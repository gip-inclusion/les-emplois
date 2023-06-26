#!/usr/bin/env python
import os
import subprocess


def normalize_filename(filename):
    # either tests.py or test_xxx.py
    # cf https://docs.djangoproject.com/en/4.2/topics/testing/overview/#writing-tests
    return filename.replace("tests_", "test_")


def compute_moves(root, files_to_move):
    target = "tests/" + root[len("itou/") :]
    target = target.removesuffix("/tests")
    target = target.replace("/tests/", "/")
    moves = []
    for filename in files_to_move:
        moves.append(
            (
                os.path.join(root, filename),
                os.path.join(target, normalize_filename(filename)),
            )
        )
    return moves


IMPORT_REWRITES = [
    (
        "from itou.openid_connect.inclusion_connect.test",
        "from tests.openid_connect.inclusion_connect.test",
    ),
    (
        "from itou.openid_connect.france_connect.test",
        "from tests.openid_connect.france_connect.test",
    ),
    (
        "from itou.employee_record.tests.common",
        "from tests.employee_record.common",
    ),
    (
        "from itou.utils.htmx.test",
        "from tests.utils.htmx.test",
    ),
    (
        "from itou.utils.test",
        "from tests.utils.test",
    ),
    (
        "from itou.www.test",
        "from tests.www.test",
    ),
    (
        "from itou.utils.storage.test",
        "from tests.utils.storage.test",
    ),
]


def rewrite_imports(origin, target):
    lines_to_write = []
    change = False
    with open(target) as f:
        for line in f:
            if line.strip().startswith("from .. "):
                double_parent = os.path.dirname(os.path.dirname(origin))
                line = line.replace("from ..", f"from {double_parent.replace('/', '.')}")
                change = True
            if line.strip().startswith("from . "):
                parent = os.path.dirname(origin)
                line = line.replace("from .", f"from {parent.replace('/', '.')}")
                change = True
            if line.strip().startswith("from ..."):
                triple_parent = os.path.dirname(os.path.dirname(os.path.dirname(origin)))
                line = line.replace("from ..", f"from {triple_parent.replace('/', '.')}")
                change = True
            if line.strip().startswith("from .."):
                double_parent = os.path.dirname(os.path.dirname(origin))
                line = line.replace("from .", f"from {double_parent.replace('/', '.')}")
                change = True
            if line.strip().startswith("from ."):
                parent = os.path.dirname(origin)
                line = line.replace("from ", f"from {parent.replace('/', '.')}")
                change = True
            for origin_import, target_import in IMPORT_REWRITES:
                if line.strip().startswith(origin_import):
                    line = line.replace(origin_import, target_import)
                    change = True
                    break
            lines_to_write.append(line)
    if change:
        with open(target, "w") as f:
            f.writelines(lines_to_write)


def create_dirs_and_move(moves):
    created_dirs = set()
    for origin, target in moves:
        target_dir = target
        while target_dir := os.path.dirname(target_dir):
            if target_dir not in created_dirs:
                print(f"Creating {target_dir}")
                created_dirs.add(target_dir)
                os.makedirs(target_dir, exist_ok=True)
                with open(os.path.join(target_dir, "__init__.py"), "w"):
                    pass

        print(f"Moving {origin} to {target}")
        subprocess.run(["git", "mv", origin, target])
        rewrite_imports(origin, target)


moves = []
for root, dirs, files in os.walk("itou"):
    if "static_collected" in root or "__pycache__" in root:
        continue
    files_to_move = []
    for filename in files:
        if filename.endswith((".html", ".js", ".json", ".pyc")):
            continue
        if (
            filename.startswith("test")  # test_*.py / tests_*.py / tests.py / test.py
            or filename == "conftest.py"
            or (filename == "common.py" and root.endswith("tests"))
        ):
            files_to_move.append(filename)
    if files_to_move:
        moves.extend(compute_moves(root, files_to_move))

create_dirs_and_move(moves)
moves = []

# Cleanup lone __init__.py files in tests directories
for root, dirs, files in os.walk("itou"):
    if root.endswith("/tests") and files == ["__init__.py"]:
        with open(os.path.join(root, files[0])) as f:
            empty = not f.read()
        if empty:
            print(f"Removing empty {root}")
            subprocess.run(["git", "rm", "-r", root])
