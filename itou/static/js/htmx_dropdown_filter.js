htmx.onLoad((target) => {
  function toggleHasSelectedItem() {
    const dropdown = this.closest('.dropdown');
    this.classList.toggle('has-selected-item', dropdown.querySelector('input:checked:not([value=""])'));
  }
  target.querySelectorAll('.btn-dropdown-filter.dropdown-toggle').forEach((dropdownFilter) => {
    dropdownFilter.addEventListener('hide.bs.dropdown', toggleHasSelectedItem);
    toggleHasSelectedItem.call(dropdownFilter);
  });
});
