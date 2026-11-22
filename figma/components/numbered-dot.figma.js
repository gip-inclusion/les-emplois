// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=7250-36565
// source=itou/templates/otp_views/enrollment_step_0_intro.html (numbered step badge)
// component=Pastille numérotée
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
// The connector line (orientation and side) belongs to the surrounding layout, not to the badge:
// both variants are read for completeness but do not change the markup.
instance.getEnum('Horizontal', { On: 'horizontal', Off: 'vertical' })
instance.getEnum('Inversé', { On: 'before', Off: 'after' })

export default {
  example: figma.html`<span class="badge badge-xl bg-tertiary text-white fw-bold rounded-circle">${text}</span>`,
  id: 'numbered-dot',
  metadata: { nestable: true },
}
