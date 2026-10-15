// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=8981-14352
// source=les-emplois itou/templates/includes/organizations/_organization_info.html (itou-theme story "Box Organization")
// component=Box structure
const figma = require('figma')
const instance = figma.selectedInstance

// The include is always collapsible; "Open" maps to its `show` argument.
// Without "Dropdown" the box cannot be folded: the closest call is the open one.
const collapsible = instance.getBoolean('Dropdown')
const open = instance.getEnum('Open', { On: true, Off: false })
const show = open || !collapsible ? ' show=True' : ''

export default {
  example: figma.html`{% include "includes/organizations/_organization_info.html" with organization=company company_show_cta=True${show} extra_box_class="mb-3 mb-md-4" only %}`,
  id: 'organization-box',
  metadata: { nestable: true },
}
