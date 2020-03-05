$(document).ready(() => {

  // Prevent multiple submit client side.
  // Never trust the client: validation must also happen server side.
  // Opt-in by adding a `js-prevent-multiple-submit` CSS class to a <form>.

  $('form.js-prevent-multiple-submit').on('submit', function () {
      $(':submit', this).on('click', function () {
          return false
      })
  })

  // Prevent a user from clicking frantically on a link.
  $('a.disable-on-click').on('click', function () {
    if ($(this).hasClass('disabled')) {
        return false
    }
    console.log('clicked');
    $(this).addClass('disabled');
  });

})
