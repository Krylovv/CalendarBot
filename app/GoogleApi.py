from google.oauth2 import service_account


class GoogleApi:
    SCOPES = [
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/spreadsheets",
    ]
    SERVICE_ACCOUNT_FILE = "./secrets/service_account.json"

    def __init__(self):
        # Service account key never expires; the short-lived access token is refreshed
        # in memory by googleapiclient, so nothing is written back to disk.
        self.creds = service_account.Credentials.from_service_account_file(
            self.SERVICE_ACCOUNT_FILE, scopes=self.SCOPES
        )
