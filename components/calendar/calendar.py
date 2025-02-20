from django_components import Component, register


@register("calendar")
class Calendar(Component):
    template_file = "calendar.html"

    def get_context_data(self):
        return {
            "date": "1970-01-01",
        }
