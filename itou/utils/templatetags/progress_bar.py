from django import template
from django.utils import timezone
from django.utils.html import format_html


register = template.Library()


@register.simple_tag
def progress_bar(obj, extra_classes="bg-success"):
    today = timezone.localdate()
    if getattr(obj, "start_date", None):
        start = obj.start_date
        end = obj.end_date
    else:
        start = obj.start_at
        end = obj.end_at
    if today < start:  # start date is in the future
        progress_percentage = 0
    elif end:  # there is a set end date
        today = timezone.localdate()
        elapsed_days = today - start
        total = end - start
        progress_percentage = elapsed_days * 100 // total
    else:  # no set end date but in progress => fill the bar a tiny bit
        progress_percentage = 1
    return format_html(
        """
        <div>
            <div class="d-flex justify-content-between">
                <strong>{}</strong>
                <strong>{}</strong>
            </div>
            <div class="progress my-1" role="progressbar" aria-valuenow="{}" aria-valuemin="0" aria-valuemax="100">
                <div class="progress-bar {}" style="width: {}%"></div>
            </div>
        </div>
        """,
        start.strftime("%d/%m/%y"),
        end and end.strftime("%d/%m/%y") or "Pas de date de fin connue",
        progress_percentage,
        extra_classes,
        progress_percentage,
    )
