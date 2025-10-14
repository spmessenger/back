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
    response = client.post('/api/chats/group', json={'participants': [participant.id], 'title': 'test'})

    assert response.status_code == 200
    resp_json = response.json()
    assert resp_json['chat']['id']
    assert resp_json['chat']['type'] == ChatType.GROUP
    assert resp_json['participants'][1]['user_id'] == client.get_user_id()
    assert resp_json['participants'][1]['role'] == ParticipantType.ADMIN
    assert resp_json['participants'][0]['user_id'] == participant.id
    assert resp_json['participants'][0]['role'] == ParticipantType.MEMBER
