from tests.conftest import client, TestClient


def test_health(client: TestClient):
    response = client.get('/health')
    assert response.status_code == 200
