// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5565-36873
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=fs-sm + underline
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="fs-sm text-decoration-underline">${text}</p>`,
  id: 'typography-fs-sm-underline',
  metadata: { nestable: true },
}
