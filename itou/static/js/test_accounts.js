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
            $('#testAccountsModal').modal();
        }
    }

    $('.postLogin').on('click', function(){
        const account_type = $(this).data('type');
        const email = $(this).data('email');
        const form = $("#testAccountsForm");
        form.find('input[type=email]').val(email);
        form.find('input[type=password]').val("password");
        form.find('input[name=account_type]').val(account_type);
        form.submit();
    });
});
