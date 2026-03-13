from django.contrib.auth.views import login_not_required
from django.shortcuts import render


@login_not_required
def show_components(request):
    context = {
        "alerts": {
            "variants": ("info", "success", "warning", "danger", "important"),
        },
        "global_alerts": {
            "variants": ("info", "danger", "warning"),
        },
    }
    return render(request, "components/index.html", context)
