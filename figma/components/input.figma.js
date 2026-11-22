// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=14590-467
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/forms-input-select-textarea--docs + forms-inputgroup--docs ; markup as rendered by {% bootstrap_field %} (django-bootstrap5) in les-emplois
// component=Input
const figma = require('figma')
const instance = figma.selectedInstance

const label = instance.getString('Label')
const value = instance.getString('Valeur')
const hasHelp = instance.getBoolean("Texte d'aide")
const state = instance.getEnum('State', {
  '01. Default': 'empty',
  '02. Focus': 'empty',
  '04. Valid': 'valid',
  '05. Error': 'error',
  '06. Disabled': 'disabled',
  '07. Filled': 'filled',
})
const size = instance.getEnum('Size', { sm: 'sm', default: '', lg: 'lg', xl: 'xl' })
const type = instance.getEnum('Type', { Normal: 'normal', 'Icône': 'icon', Addon: 'addon' })
// itou-theme only generates breakpoint-scoped width classes (.form-group-input-w-{bp}-{width}).
// lg is the breakpoint les-emplois uses for these widths (form-group-input-w-lg-66 / -lg-33).
const width = instance.getEnum('Largeur', {
  '100%': '',
  '66%': ' form-group-input-w-lg-66',
  '33%': ' form-group-input-w-lg-33',
})
const left = instance.getBoolean('Gauche')
const right = instance.getBoolean('Droite')

// The help / feedback text is not a component property: read it from the "Message" layer.
const messageLayer = hasHelp ? instance.findText('Message') : undefined
const message = messageLayer && messageLayer.type === 'TEXT' ? messageLayer.textContent : "Texte d'aide"

// No placeholder, ever: empty states render an input without value.
const showValue = state === 'valid' || state === 'error' || state === 'filled'
const valueAttr = showValue ? ` value="${value}"` : ''
const validation = state === 'valid' ? ' is-valid' : state === 'error' ? ' is-invalid' : ''
const disabled = state === 'disabled' ? ' disabled' : ''
const ariaInvalid = state === 'error' ? ' aria-invalid="true"' : ''
const describedBy = hasHelp ? ' aria-describedby="id_field_helptext"' : ''

// Every optional line carries its own leading newline + indentation, so absent parts leave no blank line.
const line = (indent, html) => (html ? `\n${' '.repeat(indent)}${html}` : '')

let feedbackHtml = ''
if (hasHelp && state === 'valid') {
  feedbackHtml = `<div class="valid-feedback" id="id_field_helptext">${message}</div>`
} else if (hasHelp && state === 'error') {
  feedbackHtml = `<div class="invalid-feedback" id="id_field_helptext">${message}</div>`
} else if (hasHelp) {
  feedbackHtml = `<div class="form-text" id="id_field_helptext">${message}</div>`
}

const iconHtml = (propName) => {
  const swap = instance.getInstanceSwap(propName)
  const name = swap && swap.type === 'INSTANCE' ? swap.name : 'error-warning-line'
  return `<span class="input-group-text"><i class="ri-${name}" aria-hidden="true"></i></span>`
}
// Addon buttons are nested "Buttons" instances: their own Code Connect template renders them.
const addonHtml = (layerName) => {
  const button = instance.findInstance(layerName)
  return button && button.type === 'INSTANCE'
    ? figma.html`
        <div class="input-group-text p-0">${button.executeTemplate().example}</div>`
    : ''
}

let example
if (type === 'normal') {
  const sizeClass = size ? ` form-control-${size}` : ''
  example = figma.html`<div class="form-group${width}">
    <label class="form-label" for="id_field">${label}</label>
    <input type="text" name="field" class="form-control${sizeClass}${validation}" id="id_field"${valueAttr}${describedBy}${ariaInvalid}${disabled}>${line(4, feedbackHtml)}
</div>`
} else {
  const groupSize = size ? ` input-group-${size}` : ''
  // Bootstrap: inside an input group, the feedback must live in .input-group.has-validation to be displayed.
  const inGroup = state === 'valid' || state === 'error'
  const hasValidation = inGroup ? ' has-validation' : ''
  const input = `<input type="text" name="field" class="form-control${validation}" id="id_field"${valueAttr}${describedBy}${ariaInvalid}${disabled}>`
  let before
  let after
  if (type === 'icon') {
    before = line(8, left ? iconHtml('↳ Icône gauche') : '')
    after = line(8, right ? iconHtml('↳ Icône droite') : '')
  } else {
    before = left ? addonHtml('Bouton gauche') : ''
    after = right ? addonHtml('Bouton droite') : ''
  }
  example = figma.html`<div class="form-group${width}">
    <label class="form-label" for="id_field">${label}</label>
    <div class="input-group${groupSize}${hasValidation}">${before}
        ${input}${after}${line(8, inGroup ? feedbackHtml : '')}
    </div>${line(4, inGroup ? '' : feedbackHtml)}
</div>`
}

export default {
  example,
  id: 'input',
  metadata: { nestable: true },
}
