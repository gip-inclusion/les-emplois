from django.template import Context, Template

from itou.utils.brand import product_name


# These assertions are deliberately literal: they are the proof that the
# user-facing product name changed when the brand mapping is updated.
def test_product_name():
    assert product_name() == "La plateforme de l’inclusion"
    assert product_name("de") == "de La plateforme de l’inclusion"
    assert product_name("à") == "à La plateforme de l’inclusion"


def test_brand_template_tag_is_builtin():
    template = Template("Bienvenue sur {% brand %}, le site {% brand 'de' %} : parlez {% brand 'à' %}.")
    assert template.render(Context()) == (
        "Bienvenue sur La plateforme de l’inclusion, le site de La plateforme de l’inclusion : "
        "parlez à La plateforme de l’inclusion."
    )
