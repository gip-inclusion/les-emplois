// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12560-4812
// source=https://gip-inclusion.github.io/itou-theme/doc/?path=/docs/components-box-partenaire--docs (also itou/templates/job_seekers_views/advisors.html)
// component=Box partenaire
const figma = require('figma')
const instance = figma.selectedInstance

const title = instance.getString('Titre')
const subtitle = instance.getString('Sous-titre')
const description = instance.getString('Description')

export default {
  example: figma.html`<div class="c-box c-box--promo-partenaire">
    <div class="row g-0">
        <div class="col-12 col-md pe-3 pe-md-4 py-3 py-md-4">
            <h3 class="text-tertiary">${title}</h3>
            <p><strong>${subtitle}</strong></p>
            <p class="fs-sm mb-4">${description}</p>
            <!-- contenu -->
        </div>
        <div class="d-none d-md-inline-flex col-md-auto align-self-end">
            <img src="{% static 'img/illustration-mon-recap.png' %}" class="img-fluid" alt="">
        </div>
    </div>
</div>`,
  id: 'box-partner',
  metadata: { nestable: true },
}
