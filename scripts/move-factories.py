import re
import subprocess
from pathlib import Path


def main():
    root = Path(__file__).parent.parent

    # Manual moves.
    subprocess.run(["git", "mv", "itou/cities/sample-cities.csv", "tests/cities/sample-cities.csv"])
    (root / "tests" / "jobs" / "data").mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "mv",
            "itou/jobs/data/appellations_test_fixture.csv",
            "tests/jobs/data/appellations_test_fixture.csv",
        ]
    )

    for factories in (root / "itou").rglob("factories.py"):
        current_name = factories.relative_to(root)
        lines = []
        changed = False
        with open(current_name) as f:
            for line in f:
                stripped_line = line.strip()
                if stripped_line.startswith("from . "):
                    mod_path = str(current_name.parent).replace("/", ".")
                    line = line.replace("from .", f"from {mod_path} ", 1)
                    changed = True
                elif stripped_line.strip().startswith("from ."):
                    mod_path = str(current_name.parent).replace("/", ".")
                    line = line.replace("from .", f"from {mod_path}.", 1)
                    changed = True
                lines.append(line)
        if changed:
            with open(current_name, "w") as f:
                f.writelines(lines)
        new_name = (root / "tests").joinpath(*current_name.parts[1:])
        subprocess.run(["git", "mv", str(current_name), str(new_name)])

    factories_import_re = re.compile(r"from itou\.\w+ import factories$")
    factories_import_as_re = re.compile(r"from itou\.\w+ import factories as \w+$")
    factories_import_others_re = re.compile(r"from itou\.\w+ import factories,")
    factories_import_others_as_re = re.compile(r"from itou\.\w+ import factories as \w+,")
    factories_re = re.compile(r"\bitou\.\w+?\.factories")

    for file in (root / "tests").rglob("*.py"):
        lines = []
        changed = False
        with open(file) as f:
            for line in f:
                if factories_import_others_as_re.search(line):
                    new_import = line.replace("itou.", "tests.", 1)
                    new_import = new_import.split(",", maxsplit=1)[0]
                    new_import += "\n"
                    lines.append(new_import)
                    line = re.sub(r"import factories as \w+,", "import ", line, count=1)
                    changed = True
                elif factories_import_others_re.search(line):
                    new_import = line.replace("itou.", "tests.", 1)
                    new_import = new_import.split(",", maxsplit=1)[0]
                    new_import += "\n"
                    lines.append(new_import)
                    line = line.replace("import factories, ", "import ")
                    changed = True
                elif (
                    factories_import_as_re.search(line)
                    or factories_import_re.search(line)
                    or factories_re.search(line)
                ):
                    line = line.replace("itou.", "tests.", 1)
                    changed = True
                lines.append(line)
        if changed:
            with open(file, "w") as f:
                f.writelines(lines)

    subprocess.run(["make", "fix"])


if __name__ == "__main__":
    main()
