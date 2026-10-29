// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=4222-20642
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-cards--docs
// component=Card
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Title text')
const description = instance.getString('Description text')
const subtitle = instance.getBoolean('Subtitle')
  ? figma.html`
        <p class="card-subtitle">${instance.getString('Subtitle text')}</p>`
  : ''
const image = instance.getBoolean('Image')
  ? figma.html`
    <img src="…" class="card-img-top" alt="">`
  : ''
const buttons = instance.getBoolean('Buttons')
  ? figma.html`
    <div class="card-footer">
        <a href="#" class="btn btn-sm btn-primary">…</a>
    </div>`
  : ''

export default {
  example: figma.html`<div class="card">${image}
    <div class="card-body">
        <h5 class="card-title">${title}</h5>${subtitle}
        <p class="card-text">${description}</p>
        <!-- Info card -->
    </div>${buttons}
</div>`,
  id: 'card',
  metadata: { nestable: true },
}
