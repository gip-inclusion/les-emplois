// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4416-21635
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-checkbox--docs ; same markup as django-bootstrap5 CheckboxInput in les-emplois
// component=Checkbox
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const checked = instance.getEnum('Etat', {
  Selected: ' checked',
  Unselected: '',
  Disabled: '',
  'Disabled Selected': ' checked',
  'Focus Selected': ' checked',
  'Focus Unselected': '',
})
const disabled = instance.getEnum('Etat', {
  Selected: '',
  Unselected: '',
  Disabled: ' disabled',
  'Disabled Selected': ' disabled',
  'Focus Selected': '',
  'Focus Unselected': '',
})
const showLabel = instance.getEnum('Label', { On: true, Off: false })

let example
if (showLabel) {
  example = figma.html`<div class="form-check">
    <input class="form-check-input" type="checkbox" name="field" id="id_field"${checked}${disabled}>
    <label class="form-check-label" for="id_field">${text}</label>
</div>`
} else {
  // No visible label: the text stays as the accessible name.
  example = figma.html`<div class="form-check">
    <input class="form-check-input" type="checkbox" name="field" id="id_field" aria-label="${text}"${checked}${disabled}>
</div>`
}

export default {
  example,
  id: 'checkbox',
  metadata: { nestable: true },
}
