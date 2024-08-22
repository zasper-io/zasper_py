import os

from zasper_backend.models.secretModel import SecretModel


class SecretsManager:
    def __init__(self):
        pass

    async def get(self, path):
        secrets = []
        secrets_arr = ["secret1", "secret2"]
        for secret in secrets_arr:
            content = SecretModel(
                id="string",
                project_id="string",
                name="string",
                value="string",
            )
            secrets.append(content)
        return secrets

    async def get_single(self, path):
        secrets = []
        secrets_arr = ["secret1", "secret2"]
        for secret in secrets_arr:
            content = SecretModel(
                id="string",
                project_id="string",
                name="string",
                value="string",
            )
            secrets.append(content)
        return secrets

    def create_secret(self, path):
        path = os.getcwd() + "/" + path
        with open(path, "a"):
            os.utime(path, None)

    def save(self, model, path):
        pass

    def delete_secret(self, path):
        pass

    def rename_secret(self, path):
        pass
