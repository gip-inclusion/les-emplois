// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12576-13694
// source=les-emplois: Complexe = itou/templates/signup/choose_user_kind.html (.c-card.has-rich-radio, also otp_views/enrollment_step_1_choose_device_type.html) ; Simple = itou/templates/signup/includes/user_kind_radio.html
// component=Radio button - Rich
const figma = require('figma')
const instance = figma.selectedInstance

const description = instance.getString('text')
const hasIllustration = instance.getBoolean('Illustration')
const checked = instance.getEnum('Active', { On: ' checked', Off: '' })
const type = instance.getEnum('Type', { Simple: 'simple', Complexe: 'complex' })

// The title is the "Text" property of the nested "Radio button" instance.
const radio = instance.findInstance('Radio button')
const title = radio && radio.type === 'INSTANCE' ? radio.getString('Text') : 'Label'

// The card body is a slot, split across variants: "Slot 3" when Active=On, "Slot" when Active=Off.
// Its default content (description + illustration) is rendered from the properties above;
// anything else dropped in the slot (e.g. a .tag-group) is appended after it.
const slot = type === 'complex' ? instance.getSlot(checked ? 'Slot 3' : 'Slot') : undefined

let illustration = ''
if (hasIllustration) {
  const art = instance.findInstance('Illustrations communes')
  const theme = art && art.type === 'INSTANCE' ? art.getEnum('Theme', { Candidat: 'candidat', Prescripteur: 'prescripteur' }) : 'candidat'
  const file = theme === 'prescripteur' ? 'illustration-signup-01.png' : 'illustration-signup-02.png'
  illustration = `
            <figure class="d-none d-md-inline-flex">
                <img src="{% static_theme_images '${file}' %}" loading="lazy" alt="" width="150">
            </figure>`
}

let example
if (type === 'complex') {
  example = figma.html`<div class="c-card card has-one-link-inside has-rich-radio h-100">
    <div class="card-header pb-3 pb-me-4">
        <div class="form-check">
            <input class="form-check-input" type="radio" name="kind" value="value" id="kind_value" required${checked}>
            <label class="form-check-label stretched-link" for="kind_value">
                <strong>${title}</strong>
            </label>
        </div>
    </div>
    <div class="card-body">
        <div class="d-flex">
            <div>
                <p>${description}</p>${slot && slot.length ? figma.html`
                ${slot}` : ''}
            </div>${illustration}
        </div>
    </div>
</div>`
} else {
  example = figma.html`<div class="c-card card my-3">
    <div class="card-body">
        <div class="form-check">
            <input class="form-check-input" type="radio" name="kind" value="value" id="kind_value" required${checked}>
            <label class="form-check-label" for="kind_value">
                <strong>${title}</strong>
                <br>
                ${description}
            </label>
        </div>
    </div>
</div>`
}

export default {
  example,
  id: 'radio-button-rich',
  metadata: { nestable: true },
}
