$(document).ready(function(){
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
