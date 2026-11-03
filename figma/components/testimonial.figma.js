// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10700-511
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/utilities-typography--docs (Quotes story, .testimonial)
// component=Testimonial
const figma = require('figma')
const instance = figma.selectedInstance

const quote = instance.getString('Citation')
const caption = instance.getBoolean('Legende')
  ? figma.html`
    <figcaption class="testimonial-footer">${instance.getString('Auteur')} · <cite>${instance.getString('Détails')}</cite></figcaption>`
  : ''

export default {
  example: figma.html`<figure>
    <blockquote class="testimonial mb-2">
        <p class="mb-0">${quote}</p>
    </blockquote>${caption}
</figure>`,
  id: 'testimonial',
  metadata: { nestable: true },
}
