from tests.conftest import client, TestClient


def test_register(client: TestClient):
    response = client.post('/api/register', json={'username': 'test', 'password': 'test'})

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json['auth']['access_token']
    assert resp_json['chats'][0]['id']
    assert resp_json['chats'][0]['type'] == 'private'


def test_login(client: TestClient):
    client.post('/api/register', json={'username': 'test', 'password': 'test'})
    response = client.post('/api/login', json={'username': 'test', 'password': 'test'})

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json['auth']['access_token']
