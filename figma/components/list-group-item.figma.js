// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=5692-36885
// source=itou/templates/companies/includes/_list_siae_actives_jobs_row.html + _card_jobdescription.html; https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-list-group--docs (RichContent)
// component=Item listgroup
const figma = require('figma')
const instance = figma.selectedInstance

// Device and State (hover) don't change the markup.
instance.getEnum('Device', { Desktop: '', Mobile: '' })
instance.getEnum('State', { Default: '', Hover: '' })
const selected = instance.getEnum('Selected', { On: ' active" aria-current="true', Off: '' })
// Condensed and the chevron are classes of the parent list (.list-group-sm, .list-group-link).
const condensed = instance.getEnum('Condensed', { Off: '', On: `
    <!-- .list-group-sm sur le <ul> parent -->` })
const descriptionFirst = instance.getEnum('Type', { 'Title first': false, 'Description first': true })
const textSize = instance.getEnum('Text Size', { Large: '', Small: ' fs-sm' })

const checkbox = instance.getBoolean('Checkbox')
  ? figma.html`
    <input class="form-check-input me-1" type="checkbox">`
  : ''
const image = instance.getBoolean('Image')
  ? figma.html`
    <!-- image -->`
  : ''
const titleIcon = instance.getBoolean('Title Icon') ? figma.html` <i class="ri-external-link-line" aria-hidden="true"></i>` : ''
const badgeLeft = instance.getBoolean('Badge left')
  ? figma.html`
        <span class="badge badge-sm rounded-pill bg-accent-03 text-primary">…</span>`
  : ''
const title = figma.html`
        <a href="#" class="fw-bold text-decoration-none stretched-link${textSize}">Intitulé${titleIcon}</a>${badgeLeft}`
const descriptionIcon = instance.getBoolean('Description Icon') ? figma.html`<i class="ri-map-pin-2-line ri-sm" aria-hidden="true"></i> ` : ''
const description = instance.getBoolean('Description')
  ? figma.html`
        <p class="fs-sm mb-0 mt-1">${descriptionIcon}Le Bouscat - 33</p>`
  : ''
const badgeRight = instance.getBoolean('Badge right')
  ? figma.html`
    <div class="badge-group d-flex flex-column align-items-end">
        <span class="badge badge-xs rounded-pill bg-accent-02-light text-primary">…</span>
    </div>`
  : ''
const arrow = instance.getBoolean('Arrow')
  ? figma.html`
    <!-- chevron : .list-group-link sur le <ul> parent -->`
  : ''

export default {
  example: figma.html`<li class="list-group-item list-group-item-action${selected}">${condensed}${checkbox}${image}
    <div>${descriptionFirst ? [description, title] : [title, description]}
    </div>${badgeRight}${arrow}
</li>`,
  id: 'list-group-item',
  metadata: { nestable: true },
}
