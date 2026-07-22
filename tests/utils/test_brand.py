from django.template import Context, Template

from itou.utils.brand import product_name


# These assertions are deliberately literal: they are the proof that the
# user-facing product name changed when the brand mapping is updated.
def test_product_name():
    assert product_name() == "Les emplois de l’inclusion"
    assert product_name("de") == "des Emplois de l’inclusion"
    assert product_name("à") == "aux Emplois de l’inclusion"


def test_brand_template_tag_is_builtin():
    template = Template("Bienvenue sur {% brand %}, le site {% brand 'de' %} : parlez {% brand 'à' %}.")
    assert template.render(Context()) == (
        "Bienvenue sur Les emplois de l’inclusion, le site des Emplois de l’inclusion : "
        "parlez aux Emplois de l’inclusion."
    )
