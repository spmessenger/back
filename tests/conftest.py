import pytest
from jose import jwt
from fastapi.testclient import TestClient
from back.app import app
from core.tests.utils import clear_in_memory_repos
from db.misc.tables import create_tables, drop_tables


class AuthTestClient(TestClient):
    def get_user_id(self):
        token = self.cookies.get('access_token')
        if not token:
            raise ValueError('access_token cookie not found')
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
    resp = client.post('/api/register', json={'email': 'test@example.com', 'verification_code': '0000'})
    resp_json = resp.json()
    client = AuthTestClient(app, cookies={'access_token': resp_json['auth']['access_token']})
    return client


@pytest.fixture(scope='function', autouse=True)
def clear_memory():
    yield
    clear_in_memory_repos()
