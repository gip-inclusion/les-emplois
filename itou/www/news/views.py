from datetime import date

from django.views.generic import TemplateView
from django.db.models import Prefetch, Q

from itou.communications.models import AnnouncementCampaign, AnnouncementItem
from itou.users.enums import UserKind


class NewsView(TemplateView):
    template_name = "news/news.html"

    def get_context_data(self):
        today = date.today()
        year_boundary = date(today.year, 1, 1)  # 1st January this year

        items = AnnouncementItem.objects.all()
        if self.request.user.kind == UserKind.JOB_SEEKER:
            items = items.filter(Q(user_kind_tags__contains=[self.request.user.kind]) | Q(user_kind_tags=[]))

        return {
            "news": AnnouncementCampaign.objects.filter(
                start_date__gte=year_boundary, start_date__lte=today
            ).prefetch_related(Prefetch("items", queryset=items))
        }
