import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow


class GoogleApi:
    def __init__(self):
        self.creds = None
        if os.path.exists("./token.json"):
            self.creds = Credentials.from_authorized_user_file("./token.json", self.SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    "./secrets/desktop_creds.json", self.SCOPES
                )
                self.creds = flow.run_local_server(port=0)
            with open("./token.json", "w") as token:
                token.write(self.creds.to_json())
    SCOPES = ["https://www.googleapis.com/auth/calendar", "https://www.googleapis.com/auth/spreadsheets"]
