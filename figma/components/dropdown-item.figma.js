// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5552-37046
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-dropdown--docs (Basic, WithHeaderAndDivider) ; les-emplois itou/templates/employee_record/includes/list_order.html (active)
// component=Dropdown Item
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Label')
const active = instance.getEnum('State', { Inactive: '', Hover: '', Active: ' active' })
// The kit's icon is fixed (list-settings-fill); spacing follows the theme's .dropdown-header icon (me-2).
const icon = instance.getEnum('Icone', { Off: '', On: '<i class="ri-list-settings-fill me-2" aria-hidden="true"></i>' })
const chevron = instance.getEnum('Chevron', { Off: '', On: '<i class="ri-arrow-drop-right-line" aria-hidden="true"></i>' })

export default {
  example: figma.html`<a class="dropdown-item${active}" href="#">${icon}${label}${chevron}</a>`,
  id: 'dropdown-item',
  metadata: { nestable: true },
}
