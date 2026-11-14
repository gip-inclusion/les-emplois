// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5360-31177
// source=itou/templates/welcoming_tour/employer.html (class from itou/static/css/itou.css)
// component=h1-hero
// Desktop hero title; les-emplois has a single hero class, no mobile-specific one
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Texte')

export default {
  example: figma.html`<h1 class="h1-hero-c1">${text}</h1>`,
  id: 'typography-h1-hero',
  metadata: { nestable: true },
}
