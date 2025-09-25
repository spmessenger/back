import uvicorn
from .app import app


def main():
    uvicorn.run(app, host='0.0.0.0', port=8000)


def dev():
    uvicorn.run('back.app:app', host='0.0.0.0', port=8000, reload=True)
