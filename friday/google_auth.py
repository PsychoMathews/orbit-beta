"""Login no Google (uma vez só). Rode: .venv\\Scripts\\python -m friday.google_auth"""
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from .paths import GOOGLE_CREDENTIALS, GOOGLE_TOKEN

CREDENTIALS = GOOGLE_CREDENTIALS
TOKEN = GOOGLE_TOKEN

SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def connected() -> bool:
    return TOKEN.exists()


def credentials() -> Credentials:
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES) if TOKEN.exists() else None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not CREDENTIALS.exists():
            raise RuntimeError("Google não conectado: falta o credentials.json na pasta de dados.")
        creds = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS), SCOPES).run_local_server(port=0)
    TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def service(name: str, version: str):
    return build(name, version, credentials=credentials(), cache_discovery=False)


if __name__ == "__main__":
    profile = service("gmail", "v1").users().getProfile(userId="me").execute()
    print(f"Google conectado: {profile['emailAddress']}")
