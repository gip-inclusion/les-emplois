import os

import markdown
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render
from django.utils.html import mark_safe


@login_not_required
def releases(request, template_name="releases/list.html"):
    """
    Render our CHANGELOG.md file in HTML
    """
    changelog_filename = os.path.join(settings.ROOT_DIR, "CHANGELOG.md")
    with open(changelog_filename, encoding="utf-8") as f:
        changelog_html = markdown.markdown(f.read())

    context = {"changelog_html": mark_safe(changelog_html)}
    return render(request, template_name, context)
