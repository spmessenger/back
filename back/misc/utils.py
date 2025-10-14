from datetime import datetime, timezone
from fastapi import Response


def set_access_token_cookie(response: Response, auth_data: dict):
    max_age = round(auth_data['acess_token_expiration'] - datetime.now(timezone.utc).timestamp())
    response.set_cookie(
        key='access_token',
        value=auth_data['access_token'],
        httponly=True,
        max_age=max_age,
        samesite='lax',
        secure=False,  # True for https only
    )


def set_refresh_token_cookie(response: Response, auth_data: dict):
    max_age = round(auth_data['refresh_token_expiration'] - datetime.now(timezone.utc).timestamp())
    response.set_cookie(
        key='refresh_token',
        value=auth_data['refresh_token'],
        httponly=True,
        max_age=max_age,
        samesite='lax',
        secure=False,  # True for https only
    )
