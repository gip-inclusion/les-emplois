import pathlib

from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render

from itou.api.documentation import DOCUMENTATIONS


CHANGELOG = (pathlib.Path(__file__).parents[2] / "api" / "changelog.md").read_text()


@login_not_required
def index(request):
    context = {
        "changelog": CHANGELOG,
        "documentations": DOCUMENTATIONS.values(),
    }
    return render(request, "api/index.html", context)
