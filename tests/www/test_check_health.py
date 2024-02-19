class TestCheckHealth:
    def test_get(self, client):
        response = client.get("/check-health")
        assert response.status_code == 200
        assert response.charset == "utf-8"
        assert response["Content-Type"] == "text/plain"
        assert response["Content-Length"] == "8"
        assert response.content.decode() == "Healthy\n"

    def test_get_as_clever(self, client):
        response = client.get(
            "/check-health",
            # CleverCloud probes connect directly through the IP, their HOST is not in the ALLOWED_HOSTS.
            HTTP_HOST="10.2.2.2",
        )
        assert response.status_code == 200

    def test_get_with_error(self, client, mocker):
        mocker.patch("itou.www.middleware.connection.cursor", side_effect=Exception("Boom!"))
        response = client.get("/check-health")
        assert response.status_code == 500
