// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8662-824
// source=itou/templates/components/c-info.html ({% component_info %}, as in apply/includes/geiq/legislative_text_link.html)
// component=Information
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Title')
const description = instance.getString('Description')
const dropdown = instance.getEnum('Dropdown', { Off: false, On: true })
const opened = instance.getEnum('↳ Open', { Off: '', On: ' opened=True' })
instance.getEnum('Hover', { Off: '', On: '' })

// Dropdown=Off shows the title only; Dropdown=On adds a collapsible detail.
const collapse = dropdown ? ` collapse_id="info-detail"${opened}` : ''
const detail = dropdown
  ? figma.html`
    {% fragment as c_info__detail %}
        <p>${description}</p>
        <!-- contenu -->
    {% endfragment %}`
  : ''

export default {
  example: figma.html`{% load components %}
{% component_info c_info__summary=c_info__summary c_info__detail=c_info__detail${collapse} %}
    {% fragment as c_info__summary %}
        ${title}
    {% endfragment %}${detail}
{% endcomponent_info %}`,
  id: 'information',
  metadata: { nestable: true },
}
