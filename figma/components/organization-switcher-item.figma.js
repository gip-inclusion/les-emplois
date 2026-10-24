// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10420-15229
// source=les-emplois itou/templates/layout/_organization_switcher_dropdown_menu.html
// component=Structure btn
const figma = require('figma')
const instance = figma.selectedInstance

// Render a nested instance through its own Code Connect template when it has one.
const nested = (layer) => {
  const child = instance.findInstance(layer)
  return child && child.type === 'INSTANCE' && child.hasCodeConnect() ? child.executeTemplate().example : undefined
}

const kind = instance.getString('Type')
const name = instance.getString('Nom')
const active = instance.getEnum('State', { Unselected: '', Selected: ' active', Hover: '' })
const icon = nested('User icon') || figma.html`<i class="ri-community-line" aria-hidden="true"></i>`

export default {
  example: figma.html`<li>
    <button type="submit" class="dropdown-item dropdown-item__summary${active}" name="organization_key" value="company-1">
        ${icon}
        <span>${kind}</span>
        <strong>${name}</strong>
    </button>
</li>`,
  id: 'organization-switcher-item',
  metadata: { nestable: true },
}
