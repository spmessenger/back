from fastapi.testclient import TestClient
from back.app import app
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
    assert resp_json[0]['title'] == '\u0418\u0437\u0431\u0440\u0430\u043d\u043d\u043e\u0435'


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


def test_unread_messages_counter_updates_and_clears(client: AuthTestClient):
    other_client = TestClient(app)
    register_resp = other_client.post(
        '/api/register', json={'username': 'test2', 'password': 'secret123'}
    )
    register_payload = register_resp.json()
    second_user_client = AuthTestClient(
        app, cookies={'access_token': register_payload['auth']['access_token']}
    )

    second_user_id = second_user_client.get_user_id()
    current_user_id = client.get_user_id()

    create_dialog_resp = client.post(
        '/api/chats/dialog', json={'participant_id': second_user_id}
    )
    chat_id = create_dialog_resp.json()['chat']['id']

    second_user_client.post('/api/chats/dialog', json={'participant_id': current_user_id})
    second_user_client.post(
        f'/api/chats/{chat_id}/messages', json={'content': 'hello from test2'}
    )

    chats_resp = client.get('/api/chats')
    chats_payload = chats_resp.json()
    dialog_chat = next(chat for chat in chats_payload if chat['id'] == chat_id)
    assert dialog_chat['unread_messages_count'] == 1

    read_resp = client.get(f'/api/chats/{chat_id}/messages')
    assert read_resp.status_code == 200

    chats_after_read_resp = client.get('/api/chats')
    chats_after_read_payload = chats_after_read_resp.json()
    dialog_chat_after_read = next(
        chat for chat in chats_after_read_payload if chat['id'] == chat_id
    )
    assert dialog_chat_after_read['unread_messages_count'] == 0


def test_get_chats_contains_last_message_preview(client: AuthTestClient):
    send_message_resp = client.post('/api/chats/1/messages', json={'content': 'hello reload'})
    assert send_message_resp.status_code == 200

    chats_resp = client.get('/api/chats')
    assert chats_resp.status_code == 200
    chats_payload = chats_resp.json()
    private_chat = next(chat for chat in chats_payload if chat['id'] == 1)

    assert private_chat['last_message'] == 'hello reload'
    assert private_chat['last_message_at']


def test_get_chats_orders_private_then_recent_last_message(client: AuthTestClient):
    participant = create_user('order-user', 'test')

    first_dialog_resp = client.post(
        '/api/chats/dialog',
        json={'participant_id': participant.id},
    )
    first_chat_id = first_dialog_resp.json()['chat']['id']
    client.post(f'/api/chats/{first_chat_id}/messages', json={'content': 'older message'})

    second_dialog_resp = client.post(
        '/api/chats/group',
        json={
            'participants': [participant.id],
            'title': 'newer chat',
        },
    )
    second_chat_id = second_dialog_resp.json()['chat']['id']
    client.post(f'/api/chats/{second_chat_id}/messages', json={'content': 'newer message'})

    chats_resp = client.get('/api/chats')
    assert chats_resp.status_code == 200
    chats = chats_resp.json()

    assert chats[0]['type'] == ChatType.PRIVATE
    non_private_chat_ids = [chat['id'] for chat in chats[1:]]
    assert non_private_chat_ids[0] == second_chat_id
    assert non_private_chat_ids[1] == first_chat_id


def test_get_chats_orders_private_then_pinned_then_recent(client: AuthTestClient):
    participant = create_user('pin-order-user', 'test')
    private_chat_id = 1

    first_group_resp = client.post(
        '/api/chats/group',
        json={
            'participants': [participant.id],
            'title': 'first group',
        },
    )
    first_group_id = first_group_resp.json()['chat']['id']

    second_group_resp = client.post(
        '/api/chats/group',
        json={
            'participants': [participant.id],
            'title': 'second group',
        },
    )
    second_group_id = second_group_resp.json()['chat']['id']

    # Make first group newer by last message time than second one
    client.post(f'/api/chats/{second_group_id}/messages', json={'content': 'older'})
    client.post(f'/api/chats/{first_group_id}/messages', json={'content': 'newer'})

    # Pin second group after first group -> second must be before first in pinned block
    pin_first_resp = client.post(f'/api/chats/{first_group_id}/pin')
    assert pin_first_resp.status_code == 200
    assert pin_first_resp.json() is True

    pin_second_resp = client.post(f'/api/chats/{second_group_id}/pin')
    assert pin_second_resp.status_code == 200
    assert pin_second_resp.json() is True

    chats_resp = client.get('/api/chats')
    assert chats_resp.status_code == 200
    chats = chats_resp.json()

    assert chats[0]['id'] == private_chat_id
    assert chats[1]['id'] == second_group_id
    assert chats[2]['id'] == first_group_id


def test_get_chat_groups_returns_empty_by_default(client: AuthTestClient):
    response = client.get('/api/chat-groups')

    assert response.status_code == 200
    assert response.json() == []


def test_replace_chat_groups_saves_only_non_private_user_chats(client: AuthTestClient):
    participant = create_user('folders-user', 'test')

    group_resp = client.post(
        '/api/chats/group',
        json={
            'participants': [participant.id],
            'title': 'group for folders',
        },
    )
    assert group_resp.status_code == 200
    group_chat_id = group_resp.json()['chat']['id']

    bad_resp = client.put(
        '/api/chat-groups',
        json={
            'groups': [
                {
                    'title': 'bad group',
                    'chat_ids': [1],  # private chat is not allowed in folders
                }
            ]
        },
    )
    assert bad_resp.status_code == 400

    save_resp = client.put(
        '/api/chat-groups',
        json={
            'groups': [
                {
                    'title': 'Work',
                    'chat_ids': [group_chat_id],
                }
            ]
        },
    )
    assert save_resp.status_code == 200
    payload = save_resp.json()
    assert len(payload) == 1
    assert payload[0]['title'] == 'Work'
    assert payload[0]['chat_ids'] == [group_chat_id]
