from django_components import Component, register


@register("badge")
class Badge(Component):
    template_file = "badge.html"

    def get_context_data(self, **kwargs):
        return {
            "extra_class": kwargs.get("extra_class", "bg-success")
        }
