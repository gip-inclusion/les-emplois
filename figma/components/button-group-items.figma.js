// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5563-37759
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-buttonsgroup--docs (Default)
// component=Button group items
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
// Placement (rounded corners) is handled by .btn-group; Hover/Focus are CSS only.
instance.getEnum('Placement', { Left: 'left', Middle: 'middle', Right: 'right' })
instance.getEnum('State', { Default: '', Hover: '', Focus: '' })
const size = instance.getEnum('Size', { S: ' btn-sm', M: '', L: ' btn-lg' })

export default {
  example: figma.html`<a href="#" class="btn${size} btn-primary">${text}</a>`,
  id: 'button-group-items',
  metadata: { nestable: true },
}
