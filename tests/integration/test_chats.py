from core.entities.chat import ChatType
from core.entities.participant import ParticipantType
from core.tests.creators import create_user
from tests.conftest import auth_client as client, AuthTestClient


def test_get_chats(client: AuthTestClient):
    response = client.get('/api/chats')

    assert response.status_code == 200
    resp_json = response.json()

    assert len(resp_json) == 1
    assert resp_json[0]['id']
    assert resp_json[0]['type'] == ChatType.PRIVATE


def test_get_available_users_requires_auth(client):
    response = client.get('/api/available-users')

    assert response.status_code == 401


def test_get_available_users_excludes_current_user_and_sensitive_fields(client: AuthTestClient):
    create_user('test2', 'test')
    create_user('test3', 'test')

    response = client.get('/api/available-users')

    assert response.status_code == 200
    resp_json = response.json()

    assert [user['username'] for user in resp_json] == ['test2', 'test3']
    assert all(user['id'] != client.get_user_id() for user in resp_json)
    assert all('hashed_password' not in user for user in resp_json)
    assert all('refresh_tokens' not in user for user in resp_json)


def test_create_dialog(client: AuthTestClient):
    participant = create_user('test2', 'test')
    response = client.post('/api/chats/dialog', json={'participant_id': participant.id})

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json['chat']['id']
    assert resp_json['chat']['type'] == ChatType.DIALOG
    assert resp_json['participants'][0]['user_id'] == client.get_user_id()
    assert resp_json['participants'][1]['user_id'] == participant.id
    assert resp_json['participants'][1]['chat_visible'] is False


def test_create_group(client: AuthTestClient):
    participant = create_user('test2', 'test')

    response = client.post(
        '/api/chats/group',
        json={
            'participants': [participant.id],
            'title': 'test',
            'avatar': {
                'data_url': 'data:image/png;base64,test-avatar',
                'stage_size': 360,
                'crop_x': 10,
                'crop_y': 10,
                'crop_size': 120,
            },
        },
    )

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json['chat']['id']
    assert resp_json['chat']['type'] == ChatType.GROUP
    assert resp_json['chat']['avatar_url'].startswith('data:image/png;base64,')
    assert resp_json['participants'][1]['user_id'] == client.get_user_id()
    assert resp_json['participants'][1]['role'] == ParticipantType.ADMIN
    assert resp_json['participants'][0]['user_id'] == participant.id
    assert resp_json['participants'][0]['role'] == ParticipantType.MEMBER
