from tests.mon_recap.factories import NotebookOrderFactory


class TestNotebookOrderModel:
    def test_notebook_order_with_coworkers_emails(self):
        notebook_order = NotebookOrderFactory(with_coworkers_emails=True)
        assert notebook_order.with_coworkers_distribution is True
        assert len(notebook_order.coworkers_emails) == 2

    def test_notebook_order_with_obstacles(self):
        notebook_order = NotebookOrderFactory(with_obstacles=True)
        assert len(notebook_order.public_main_obstacles) == 3
