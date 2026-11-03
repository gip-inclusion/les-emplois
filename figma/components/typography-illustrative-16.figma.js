// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5682-36442
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=Illustrative 16px
// Illustrative font (.ff-extra-01) at 16px ($font-size-base)
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="ff-extra-01 fs-base">${text}</p>`,
  id: 'typography-illustrative-16',
  metadata: { nestable: true },
}
