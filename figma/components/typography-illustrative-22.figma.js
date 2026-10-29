// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5682-36444
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs
// component=Illustrative 22px
// Illustrative font (.ff-extra-01); the theme has no 22px size, .fs-2 (24px) is the closest step above
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<p class="ff-extra-01 fs-2">${text}</p>`,
  id: 'typography-illustrative-22',
  metadata: { nestable: true },
}
