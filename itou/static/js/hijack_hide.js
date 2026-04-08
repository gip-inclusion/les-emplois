"use strict";

function ready(fn) {
  if (document.readyState !== 'loading') {
    fn();
  } else {
    document.addEventListener('DOMContentLoaded', fn);
  }
}

ready(() => {
  document.addEventListener("click", function (event) {
    const hideButton = event.target.closest("#hide-btn");
    if (hideButton) {
      document.getElementById("djhj").style.display = "none";
    }
  });
});
