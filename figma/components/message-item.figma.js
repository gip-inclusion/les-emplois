// url=https://www.figma.com/design/yhUDpqfUinkGXN6zgpJVUQ/UI-Kit?node-id=12250-2004
// source=itou/templates/apply/includes/job_application_comments_list.html (ul.list-note > li, location "tab", delete modal left out)
// component=Message item
const figma = require('figma')
const instance = figma.selectedInstance

const date = instance.getString('Date')
const name = instance.getString('Nom')
const message = instance.getString('Message')
const isYou = instance.getEnum('User', { You: true, Other: false })

export default {
  example: figma.html`<li${isYou ? ' class="is-current-user"' : ''}>
    <i class="ri-user-line"></i>
    <div>
        <div class="d-flex justify-content-between align-items-start">
            <div>
                <time datetime="…">${date}</time>
                <strong>${name}${isYou ? ' (vous)' : ''}</strong>
            </div>
        </div>
        <blockquote class="blockquote">
            <div class="collapse show">
                <p class="mb-0">${message}</p>
            </div>
        </blockquote>
    </div>
</li>`,
  id: 'message-item',
  metadata: { nestable: true },
}
