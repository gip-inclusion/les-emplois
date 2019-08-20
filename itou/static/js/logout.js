$(document).ready(() => {

  // The user is logged out only when the confirmation is received by means of a POST request.
  // This automatically turns a click on the logout link into a POST.
  // https://django-allauth.readthedocs.io/en/latest/views.html#logout-account-logout

  let logoutLink = $('#js-logout')
  let actionUrl = logoutLink.attr('href')
  let csrfToken = $('meta[name=csrf-token]').attr('content')

  logoutLink
    .on('click', e => {
      e.preventDefault()
      let input = `<input type="hidden" name="csrfmiddlewaretoken" value="${csrfToken}">`
      $(`<form action="${actionUrl}" method="post">${input}</form>`).submit()
    })

})
