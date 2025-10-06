import pytest
from fastapi.testclient import TestClient
from back.app import app
from core.tests.utils import clear_in_memory_repos


@pytest.fixture(scope='session')
def client():
    return TestClient(app)


@pytest.fixture(scope='function', autouse=True)
def clear_memory():
    yield
    clear_in_memory_repos()
