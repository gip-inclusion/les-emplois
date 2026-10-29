// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5616-36754
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=fs-xs
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="fs-xs">${text}</p>`,
  id: 'typography-fs-xs',
  metadata: { nestable: true },
}
