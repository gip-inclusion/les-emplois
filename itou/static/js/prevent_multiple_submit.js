htmx.onLoad((target) => {

  // Prevent multiple submit client side.
  // Never trust the client: validation must also happen server side.
  // Opt-in by adding a `js-prevent-multiple-submit` CSS class to a <form>.

  // Pay attention: in multi-step forms, the browser will remember the disabled
  // state of the button when clicking "Previous" in the browser, eventually
  // disabling moving forward afterwards !

  $('form.js-prevent-multiple-submit', target).on('submit', function() {
    $(':submit', this).on('click', function() {
      return false
    })
  });

})
