from django.db.models import Count, Prefetch, Q
from django.urls import reverse
from django.utils import timezone
from django.views.generic import TemplateView

from itou.communications.models import AnnouncementCampaign, AnnouncementItem
from itou.users.enums import UserKind
from itou.utils.auth import LoginNotRequiredMixin
from itou.utils.pagination import pager
from itou.utils.urls import get_safe_url


class NewsView(LoginNotRequiredMixin, TemplateView):
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

        news_page = pager(campaigns, self.request.GET.get("page"), items_per_page=12)
        return {"back_url": get_safe_url(self.request, "back_url", reverse("home:hp")), "news_page": news_page}
