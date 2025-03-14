from django_components import component
from django_components.dependencies import set_component_attrs_for_js_and_css


def patch_the_components_monkey():
    # Disable extra comment "<!-- _RENDERED Title_def2ec,L2Rk5F,, -->" injection before the component
    component.insert_component_dependencies_comment = lambda content, *args, **_kwargs: content
    # Disable extra attributes injection (used for JS & CSS integration that we don't use)
    component.set_component_attrs_for_js_and_css = (
        lambda html_content,
        component_id,
        css_input_hash,
        css_scope_id,
        root_attributes: set_component_attrs_for_js_and_css(
            html_content, component_id=None, css_input_hash=None, css_scope_id=None, root_attributes=root_attributes
        )
    )
