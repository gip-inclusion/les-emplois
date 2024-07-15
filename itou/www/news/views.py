from datetime import date

from django.views.generic import TemplateView

from itou.communications.models import AnnouncementCampaign


class NewsView(TemplateView):
    template_name = "news/news.html"

    def get_context_data(self):
        today = date.today()
        year_boundary = date(today.year, 1, 1)  # 1st January this year

        return {
            "news": AnnouncementCampaign.objects.filter(
                start_date__gte=year_boundary, start_date__lte=today
            ).prefetch_related("items")
        }
