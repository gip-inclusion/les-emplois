// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12560-112
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-accordion--docs
// component=Accordion item
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Titre')
const content = instance.getString('Contenu')
const active = instance.getEnum('Active', { On: true, Off: false })
// Top / Middle / Bottom only change the corner radii, handled by the .accordion CSS.
instance.getEnum('Order', { Top: '', Middle: '', Bottom: '' })

export default {
  example: figma.html`<div class="accordion-item">
    <button class="accordion-button${active ? '' : ' collapsed'}" type="button" data-bs-toggle="collapse" data-bs-target="#accordion-item-1" aria-expanded="${active ? 'true' : 'false'}" aria-controls="accordion-item-1">
        ${title}
    </button>
    <div id="accordion-item-1" class="accordion-collapse collapse${active ? ' show' : ''}" data-bs-parent="#accordion">
        <div class="accordion-body">${content}</div>
    </div>
</div>`,
  id: 'accordion-item',
  metadata: { nestable: true },
}
