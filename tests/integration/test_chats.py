from core.entities.chat import ChatType
from tests.conftest import auth_client as client, TestClient


def test_get_chats(client: TestClient):
    response = client.get('/api/chats')

    assert response.status_code == 200
    resp_json = response.json()

    assert resp_json[0]['id']
    assert resp_json[0]['type'] == ChatType.PRIVATE
