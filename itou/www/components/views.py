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


@login_not_required
def demo_buttons_form(request):
    context = {"reset_url": request.GET.get("reset_url")}
    return render(request, "components/demo_buttons_form.html", context)
