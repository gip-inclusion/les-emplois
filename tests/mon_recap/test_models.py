from tests.mon_recap.factories import NotebookOrderFactory


def test_notebook_order_in_qpv_or_zrr():
    notebook_order = NotebookOrderFactory(in_qpv=True)
    assert notebook_order.organization_is_in_qpv_or_zrr == "Oui, QPV"

    notebook_order = NotebookOrderFactory(in_zrr=True)
    assert notebook_order.organization_is_in_qpv_or_zrr == "Oui, ZRR"


def test_notebook_order_with_coworkers_emails():
    notebook_order = NotebookOrderFactory(with_coworkers_emails=True)
    assert notebook_order.coworkers_will_distribute
    assert len(notebook_order.coworkers_emails) == 1
