"""Shared Firestore connection for the Aria reviews prototype.

Credentials are never stored in this repository. Pick one:

  1. Real Firebase project: download a service-account key (Firebase console > Project
     settings > Service accounts > Generate new private key), save it OUTSIDE the repo
     (or under a gitignored name such as serviceAccountKey.json), then
         export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json       (Git Bash)
         $env:GOOGLE_APPLICATION_CREDENTIALS = 'C:\\path\\to\\key.json' (PowerShell)
     The project id is read from the key file.

  2. Local Firestore emulator (no key, no cloud): start it with
         npx firebase-tools emulators:start --only firestore --project demo-aria
     then  export FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
"""
import os
import sys
import warnings

# google-api-core warns on every import under Python 3.10; the prototype works there, but
# Python 3.11+ is recommended (README).
warnings.filterwarnings('ignore', message='You are using a non-supported Python version', category=FutureWarning)

import firebase_admin                                   # noqa: E402
from firebase_admin import credentials, firestore       # noqa: E402
from google.auth.credentials import AnonymousCredentials  # noqa: E402
from google.cloud import firestore as gcf               # noqa: E402

COLLECTION = 'reviews'
REPLIES = 'replies'
_client = None


def get_db():
    """Return a Firestore client, or exit with setup instructions if no credentials are configured."""
    global _client
    if _client is not None:
        return _client
    emulator = os.environ.get('FIRESTORE_EMULATOR_HOST')
    key_path = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if emulator:
        # The emulator accepts any "demo-" project id and needs no credentials, but the
        # Admin SDK still looks for some; talk to it with the Firestore client directly.
        project = os.environ.get('FIREBASE_PROJECT_ID', 'demo-aria')
        _client = gcf.Client(project=project, credentials=AnonymousCredentials())
        print(f'[firestore] emulator at {emulator}, project {project}')
    elif key_path:
        if not os.path.isfile(key_path):
            sys.exit(f'GOOGLE_APPLICATION_CREDENTIALS points to a missing file: {key_path}')
        cred = credentials.Certificate(key_path)
        firebase_admin.initialize_app(cred)
        _client = firestore.client()
        print(f'[firestore] Firebase project {cred.project_id}')
    else:
        sys.exit('No Firestore credentials. Set GOOGLE_APPLICATION_CREDENTIALS to a service-account '
                 'key file, or FIRESTORE_EMULATOR_HOST to use the local emulator. See README.md.')
    return _client
