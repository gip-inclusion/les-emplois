from django.contrib.auth.decorators import login_not_required
from django.shortcuts import render

from itou.status import models, probes


@login_not_required
def index(request):
    probes_classes = sorted(probes.get_probes_classes(), key=lambda p: p.name)
    probes_status_by_name = {ps.name: ps for ps in models.ProbeStatus.objects.all()}
    statuses = [(probe.verbose_name, probes_status_by_name.get(probe.name)) for probe in probes_classes]

    return render(request, "status/index.html", {"statuses": statuses})
