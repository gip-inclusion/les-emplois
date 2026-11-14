// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10420-15210
// source=les-emplois itou/templates/layout/_organization_switcher_offcanvas.html (rendered by {% organization_switcher mode="mobile" %} in layout/_header_authenticated.html)
// component=Structure dropdown
const figma = require('figma')
const instance = figma.selectedInstance

// Render a nested instance through its own Code Connect template when it has one.
const nested = (layer) => {
  const child = instance.findInstance(layer)
  return child && child.type === 'INSTANCE' && child.hasCodeConnect() ? child.executeTemplate().example : undefined
}

// Without "Dropdown", the user belongs to a single organization: no menu, a plain <div>.
const hasMenu = instance.getBoolean('Dropdown')
const expanded = instance.getEnum('State', { Default: 'false', Active: 'true' })
const icon = nested('User icon') || figma.html`<i class="ri-community-line" aria-hidden="true"></i>`

let example
if (hasMenu) {
  example = figma.html`<button type="button" class="dropdown-toggle dropdown-toggle__summary" data-bs-toggle="dropdown" aria-haspopup="true" aria-controls="switchOrganizationDropdownMobile" aria-expanded="${expanded}">
    ${icon}
    <span>ETTI</span>
    <strong>Une nouvelle chance</strong>
</button>
<div class="dropdown-menu" id="switchOrganizationDropdownMobile">
    {% include "layout/_organization_switcher_dropdown_menu.html" %}
</div>`
} else {
  example = figma.html`<div class="dropdown-toggle dropdown-toggle__summary">
    ${icon}
    <span>ETTI</span>
    <strong>Une nouvelle chance</strong>
</div>`
}

export default {
  example,
  id: 'organization-switcher-toggle',
  metadata: { nestable: true },
}
