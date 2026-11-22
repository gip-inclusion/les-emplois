// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=2918-6559
// source=itou/templates/includes/pagination.html
// component=Pagination
const figma = require('figma')
const instance = figma.selectedInstance

// Current page out of 3: the first one, one in between, or the last one.
const current = instance.getEnum('Etat', { Default: 1, Active: 2, Last: 3 })
const last = 3
const edge = (label, number, disabled) =>
  disabled
    ? `<li class="page-item disabled">
            <a class="page-link" aria-disabled="true" tabindex="-1" href="?page=${number}">${label}</a>
        </li>`
    : `<li class="page-item">
            <a class="page-link" href="?page=${number}">${label}</a>
        </li>`
const pageItem = (i) =>
  i === current
    ? `<li class="page-item active">
            <a class="page-link" aria-label="Page ${i}" aria-current="page" href="?page=${i}">${i}</a>
        </li>`
    : `<li class="page-item">
            <a class="page-link" aria-label="Page ${i}" href="?page=${i}">${i}</a>
        </li>`
const pages = [1, 2, 3].map(pageItem).join('\n        ')

export default {
  example: figma.html`{% include "includes/pagination.html" with page=page %}
{# Renders: #}
<nav role="navigation" aria-label="Pagination">
    <ul class="pagination flex-wrap justify-content-center">
        ${edge('Premier', 1, current === 1)}
        ${pages}
        ${edge('Dernier', last, current === last)}
    </ul>
</nav>`,
  id: 'pagination',
  metadata: { nestable: true },
}
