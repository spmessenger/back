import types
import pytest
from jose import jwt
from fastapi.testclient import TestClient
from back.app import app
from core.tests.utils import clear_in_memory_repos
from db.misc.tables import create_tables, drop_tables


class AuthTestClient(TestClient):
    def get_user_id(self):
        authorization = self.headers.get('Authorization')
        if not authorization:
            raise ValueError('Authorization header not found')
        token = authorization.split(' ')[1]
        payload = jwt.decode(token, key='', options={'verify_signature': False})
        return payload['id']


@pytest.fixture(scope='function', autouse=True)
def init_db():
    create_tables()
    yield
    drop_tables()


@pytest.fixture(scope='function')
def client():
    return TestClient(app)


@pytest.fixture(scope='function')
def auth_client(client: TestClient):
    resp = client.post('/api/register', json={'username': 'test', 'password': 'test'})
    resp_json = resp.json()
    headers = {'Authorization': f'Bearer {resp_json["auth"]["access_token"]}'}
    client = AuthTestClient(app, headers=headers)
    return client


@pytest.fixture(scope='function', autouse=True)
def clear_memory():
    yield
    clear_in_memory_repos()
