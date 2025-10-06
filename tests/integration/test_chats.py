from core.entities.chat import ChatType
from tests.conftest import client, TestClient


def test_get_chats(client: TestClient):
    client.post('/api/register', json={'username': 'test', 'password': 'test'})
    response = client.get('/api/chats')

    assert response.status_code == 200
    resp_json = response.json()

    assert resp_json['chats'][0]['id']
    assert resp_json['chats'][0]['type'] == ChatType.PRIVATE
