from django.shortcuts import render

from . import models, probes


def index(request):
    probes_classes = sorted(probes.get_probes_classes(), key=lambda p: p.name)
    probes_status_by_name = {ps.name: ps for ps in models.ProbeStatus.objects.all()}
    statuses = [(probe.verbose_name, probes_status_by_name.get(probe.name)) for probe in probes_classes]

    return render(request, "status/index.html", {"statuses": statuses})
