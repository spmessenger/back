from core.entities.chat import ChatType
from tests.conftest import client, TestClient


def test_register(client: TestClient):
    response = client.post('/api/register', json={'username': 'test', 'password': 'test'})

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json['auth']['access_token']
    assert resp_json['chats'][0]['id']
    assert resp_json['chats'][0]['type'] == ChatType.PRIVATE


def test_login(client: TestClient):
    client.post('/api/register', json={'username': 'test', 'password': 'test'})
    response = client.post('/api/login', json={'username': 'test', 'password': 'test'})

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json['auth']['access_token']


def test_get_profile(auth_client: TestClient):
    response = auth_client.get('/api/profile')

    assert response.status_code == 200
    assert response.json()['username'] == 'test'


def test_update_profile(auth_client: TestClient):
    response = auth_client.patch('/api/profile', json={'username': 'updated'})

    assert response.status_code == 200
    assert response.json()['username'] == 'updated'


def test_update_profile_rejects_duplicate_username(client: TestClient, auth_client: TestClient):
    client.post('/api/register', json={'username': 'taken', 'password': 'test'})

    response = auth_client.patch('/api/profile', json={'username': 'taken'})

    assert response.status_code == 400
