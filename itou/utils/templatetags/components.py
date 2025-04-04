from django import template
from slippers.template import slippers_token_kwargs
from slippers.templatetags.slippers import ComponentNode


register = template.Library()


def create_component_tag(template_path):
    def do_component(parser, token):
        tag_name, *remaining_bits = token.split_contents()

        # This function comes directly from https://github.com/mixxorz/slippers/blob/0.6.2/slippers/templatetags/slippers.py#L23-L29
        # but changed from here:

        # Expect a closing tag
        nodelist = parser.parse((f"end{tag_name}",))
        parser.delete_first_token()

        # to here
        # Hopefully we might use an other solution if https://github.com/mixxorz/slippers/pull/74 is merged one day

        # Bits that are not keyword args are interpreted as `True` values
        all_bits = [bit if "=" in bit else f"{bit}=True" for bit in remaining_bits]

        raw_attributes = slippers_token_kwargs(all_bits, parser)

        # Allow component fragment to be assigned to a variable
        target_var = None
        if len(remaining_bits) >= 2 and remaining_bits[-2] == "as":
            target_var = remaining_bits[-1]

        return ComponentNode(
            tag_name=tag_name,
            nodelist=nodelist,
            template_path=template_path,
            raw_attributes=raw_attributes,
            origin_template_name=parser.origin.template_name,
            origin_lineno=token.lineno,
            target_var=target_var,
        )

    return do_component


register.tag("component_title", create_component_tag("components/c-title.html"))
