from django import template


register = template.Library()


@register.simple_tag
def can_create_antenna(request):
    if request.user.is_employer and request.current_organization:
        return request.user.can_create_siae_antenna(parent_siae=request.current_organization)
    return False
