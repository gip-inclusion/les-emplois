// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5682-36443
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=Illustrative 20px
// Illustrative font (.ff-extra-01) at 20px (.fs-3 = $h3-font-size)
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="ff-extra-01 fs-3">${text}</p>`,
  id: 'typography-illustrative-20',
  metadata: { nestable: true },
}
