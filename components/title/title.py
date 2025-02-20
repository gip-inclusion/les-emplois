from django_components import Component, register


@register("title")
class Title(Component):
    template_file = "title.html"
