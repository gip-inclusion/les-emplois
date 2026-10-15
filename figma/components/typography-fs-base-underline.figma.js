// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=7142-35371
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=fs-base + underline
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="fs-base text-decoration-underline">${text}</p>`,
  id: 'typography-fs-base-underline',
  metadata: { nestable: true },
}
