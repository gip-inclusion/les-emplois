// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5552-37062
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-dropdown--docs (WithHeaderAndDivider) ; les-emplois itou/templates/layout/_header_user_dropdown_menu.html
// component=Dropdown menu
const figma = require('figma')
const instance = figma.selectedInstance

// Each child is a "Dropdown Item" instance, rendered by dropdown-item.figma.js.
const items = instance.findConnectedInstances((node) => node.name === 'Dropdown Item').map((node) => figma.html`<li>${node.executeTemplate().example}</li>`)

export default {
  example: figma.html`<div class="dropdown-menu">
    <ul class="list-unstyled mb-0">
        ${items}
    </ul>
</div>`,
  id: 'dropdown-menu',
  metadata: { nestable: true },
}
