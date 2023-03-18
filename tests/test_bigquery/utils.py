import pathlib
import os
import json

AUTH = {
    "type": "service_account",
    "project_id": "pydapper",
    "private_key_id": "08c8a357ab549f6d34f1705512bdb00c2efaf68f",
    "private_key": os.getenv("GOOGLE_PRIVATE_KEY", "DUMMY").replace("\\n", "\n"),
    "client_email": "pydapper@pydapper.iam.gserviceaccount.com",
    "client_id": "105936813038399443987",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/pydapper%40pydapper.iam.gserviceaccount.com"
}


def write_auth_file():
    this_dir = pathlib.Path(__file__).parent
    auth_dir = this_dir / "auth"

    with open(auth_dir / "key.json", "w") as auth_file:
        json.dump(AUTH, auth_file)
