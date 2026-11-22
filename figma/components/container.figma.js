// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=7051-42446
// source=itou/templates/404.html
// component=Container
const figma = require('figma')

export default {
  example: figma.html`<section class="s-section">
    <div class="s-section__container container">
        <div class="s-section__row row">
            <div class="s-section__col col-12">
                <!-- contenu -->
            </div>
        </div>
    </div>
</section>`,
  id: 'container',
  metadata: { nestable: true },
}
