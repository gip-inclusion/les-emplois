// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5360-31171
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=fs-sm
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="fs-sm">${text}</p>`,
  id: 'typography-fs-sm',
  metadata: { nestable: true },
}
