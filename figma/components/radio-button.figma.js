// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5354-32504
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-radio--docs ; same markup as django-bootstrap5 RadioSelect options in les-emplois
// component=Radio button
const figma = require('figma')
const instance = figma.selectedInstance

const text = instance.getString('Text')
const checked = instance.getEnum('Etat', {
  Disabled: '',
  Selected: ' checked',
  Unselected: '',
  'Disabled Selected': ' checked',
  'Focus Selected': ' checked',
  'Focus Unselected': '',
})
const disabled = instance.getEnum('Etat', {
  Disabled: ' disabled',
  Selected: '',
  Unselected: '',
  'Disabled Selected': ' disabled',
  'Focus Selected': '',
  'Focus Unselected': '',
})
const showLabel = instance.getEnum('Label', { On: true, Off: false })

let example
if (showLabel) {
  example = figma.html`<div class="form-check">
    <input class="form-check-input" type="radio" name="field" value="1" id="id_field_0"${checked}${disabled}>
    <label class="form-check-label" for="id_field_0">${text}</label>
</div>`
} else {
  // No visible label: the text stays as the accessible name.
  example = figma.html`<div class="form-check">
    <input class="form-check-input" type="radio" name="field" value="1" id="id_field_0" aria-label="${text}"${checked}${disabled}>
</div>`
}

export default {
  example,
  id: 'radio-button',
  metadata: { nestable: true },
}
