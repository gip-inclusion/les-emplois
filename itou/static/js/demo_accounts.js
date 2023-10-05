function supports_local_storage() {
    try {
        return 'localStorage' in window && window['localStorage'] !== null;
    } catch(e){
        return false;
    }
}

$(document).ready(function(){
    if (supports_local_storage()) {
        infoKey = localStorage.getItem("testAccountsModal");
        if (!infoKey) {
            localStorage.setItem("testAccountsModal", true);
            const testAccountsModal = new bootstrap.Modal("#testAccountsModal");
        }
    }

    $('.postLogin').on('click', function(){
        const actionUrl = $(this).data('action-url');
        const email = $(this).data('email');
        const form = $("#testAccountsForm");
        form.attr('action', actionUrl);
        form.find('input[type=email]').val(email);
        form.find('input[type=password]').val("password");
        form.find('input[name=demo_banner_account]').val(true);
        form.submit();
    });
});
