import requests

class IntuneClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.token = self._authenticate(tenant_id, client_id, client_secret)

    def _authenticate(self, tenant_id, client_id, client_secret) -> str:
        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        response = requests.post(url, data=data)
        response.raise_for_status()
        return response.json()["access_token"]

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"}

    def get_napt_apps ():
        """
        Retrieves a list of Intune apps published by Not a Pkg Tool.
        """

    def get_napt_app (app_id):
        """
        Retrieves a specific Intune app published by Not a Pkg Tool by its ID.
        """


