// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4416-21576
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-checkbox--docs (bare .form-check-input, shared by checkbox and radio)
// component=bouton radio & Check
const figma = require('figma')
const instance = figma.selectedInstance

// Building block of "Checkbox" / "Radio button": the bare control, without its .form-check wrapper or label.
const type = instance.getEnum('Type', { Check: 'checkbox', Radio: 'radio' })
const checked = instance.getEnum('Active', { On: ' checked', Off: '' })

export default {
  example: figma.html`<input class="form-check-input" type="${type}" name="field" id="id_field"${checked}>`,
  id: 'form-check-control',
  metadata: { nestable: true },
}
