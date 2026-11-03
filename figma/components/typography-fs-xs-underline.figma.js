// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5616-36753
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=fs-xs + underline
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="fs-xs text-decoration-underline">${text}</p>`,
  id: 'typography-fs-xs-underline',
  metadata: { nestable: true },
}
