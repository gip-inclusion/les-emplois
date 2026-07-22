"""Single source of truth for the product name.

The whole name, article included, is treated as an invariant proper noun
(capital initial even mid-sentence). The "de" and "à" forms exist because
the article contraction depends on the name's gender and number: renaming
the product only requires updating this mapping.
"""

FORMS = {
    None: "Les emplois de l’inclusion",
    "de": "des Emplois de l’inclusion",
    "à": "aux Emplois de l’inclusion",
}


def product_name(prep=None):
    return FORMS[prep]
