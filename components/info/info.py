from django_components import Component, register


@register("info")
class Info(Component):
    template_file = "info.html"

    def get_context_data(self, **kwargs):
        return {
            "extra_class": kwargs.get("extra_class", "bg-success"),
            "collapsibleID": kwargs.get("collapsibleID", "collapseInfoExampleDJC"),
        }
