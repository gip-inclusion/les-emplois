// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=6488-38027
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-buttonsgroup--docs (ActionGroup) ; les-emplois itou/templates/hijack/notification.html
// component=Action group
const figma = require('figma')
const instance = figma.selectedInstance

// Each child is a "Buttons" instance (Icon=Only), rendered by buttons.figma.js.
const buttons = instance.findConnectedInstances((node) => node.name === 'Buttons').map((node) => node.executeTemplate().example)

export default {
  example: figma.html`<div class="btn-group btn-group-action btn-group-sm" role="group" aria-label="Actions rapides">
    ${buttons}
</div>`,
  id: 'action-group',
  metadata: { nestable: true },
}
