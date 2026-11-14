// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5563-37838
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-buttonsgroup--docs (Default)
// component=Button group
const figma = require('figma')
const instance = figma.selectedInstance

const size = instance.getEnum('Size', { S: ' btn-group-sm', M: '', L: ' btn-group-lg' })
// Each child is a "Button group items" instance, rendered by button-group-items.figma.js.
const items = instance.findConnectedInstances((node) => node.name === 'Button group items').map((node) => node.executeTemplate().example)

export default {
  example: figma.html`<div class="btn-group${size}" role="group" aria-label="Description du groupe">
    ${items}
</div>`,
  id: 'button-group',
  metadata: { nestable: true },
}
