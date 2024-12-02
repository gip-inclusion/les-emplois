from django import template

from itou.companies.enums import CompanyKind


register = template.Library()


@register.filter(is_safe=False)
def worker_denomination(company):
    """
    Return the denomination of a worker for the company, i.e "salarié" or "travailleur indépendant".
    """
    return "travailleur indépendant" if company.kind == CompanyKind.EITI else "salarié"
