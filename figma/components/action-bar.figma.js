// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=10434-1187
// source=itou-theme stories/ItouBoxAction.stories.js (BarreActionStandard), used in les-emplois itou/templates/apply/includes/siae_actions.html
// component=Barre d'action
const figma = require('figma')
const instance = figma.selectedInstance

const actionC = instance.getBoolean('Action C')
const actionD = instance.getBoolean('Action D')

const linkAction = actionC
  ? `
        <div class="form-group col-12 col-lg-auto">
            <a href="…" class="btn btn-lg btn-link-white btn-block btn-ico">
                <i class="ri-check-line fw-medium" aria-hidden="true"></i>
                <span>Action C</span>
            </a>
        </div>`
  : ''
const dropdownAction = actionD
  ? `
        <div class="form-group col-12 col-lg d-lg-flex justify-content-lg-end">
            <div class="dropdown">
                <button id="other_actions" class="btn btn-lg btn-link-white btn-block w-lg-auto dropdown-toggle" type="button" aria-haspopup="true" aria-expanded="false" data-bs-toggle="dropdown">
                    Action D
                </button>
                <div class="dropdown-menu dropdown-menu-lg-end" aria-labelledby="other_actions">
                    <a class="dropdown-item" href="…">…</a>
                </div>
            </div>
        </div>`
  : ''

export default {
  example: figma.html`<div class="c-box c-box--action">
    <h2 class="visually-hidden">Actions rapides</h2>
    <div class="form-row align-items-center gx-3">
        <div class="form-group col-12 col-lg-auto">
            <a href="…" class="btn btn-lg btn-white btn-block btn-ico">
                <i class="ri-check-line fw-medium" aria-hidden="true"></i>
                <span>Action A</span>
            </a>
        </div>
        <div class="form-group col-12 col-lg-auto">
            <a href="…" class="btn btn-lg btn-outline-white btn-block btn-ico">
                <i class="ri-check-line fw-medium" aria-hidden="true"></i>
                <span>Action B</span>
            </a>
        </div>${linkAction}${dropdownAction}
    </div>
</div>`,
  id: 'action-bar',
  metadata: { nestable: true },
}
