function supports_local_storage() {
    try {
        return 'localStorage' in window && window['localStorage'] !== null;
    } catch(e){
        return false;
    }
}

if (supports_local_storage()) {
    infoKey = localStorage.getItem("infoModal");
    if (!infoKey) {
        localStorage.setItem("infoModal", true);
        $('#infoModal').modal();
    }
}
