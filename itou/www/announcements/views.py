from django.db.models import Count, Prefetch, Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from itou.communications.models import AnnouncementCampaign, AnnouncementItem
from itou.users.enums import UserKind
from itou.utils.constants import ITOU_HELP_CENTER_URL
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url


class NewsView(TemplateView):
    template_name = "announcements/news.html"

    def get_context_data(self):
        items = AnnouncementItem.objects.all()
        if self.request.user.is_authenticated and self.request.user.kind == UserKind.JOB_SEEKER:
            items = items.filter(Q(user_kind_tags__contains=[self.request.user.kind]) | Q(user_kind_tags=[]))

        campaigns = (
            AnnouncementCampaign.objects.filter(start_date__lte=timezone.localdate(), live=True)
            .prefetch_related(Prefetch("items", queryset=items))
            .annotate(count_items=Count("items", filter=Q(items__in=items.values_list("pk", flat=True))))
            .exclude(count_items=0)
            .order_by("-start_date")
        )

        if not campaigns.count():
            raise AnnouncementCampaign.DoesNotExist()

        news_page = pager(campaigns, self.request.GET.get("page"), items_per_page=12)
        return {"back_url": get_safe_url(self.request, "back_url", reverse("home:hp")), "news_page": news_page}

    def get(self, request, *args, **kwargs):
        try:
            return super().get(request, *args, **kwargs)
        except AnnouncementCampaign.DoesNotExist:
            # TODO: this redirect can be removed once there is guaranteed news for all users
            # the purpose is to avoid serving a blank page, on production
            return redirect(f"{ ITOU_HELP_CENTER_URL }/categories/25225629682321--Nouveaut%C3%A9s")
