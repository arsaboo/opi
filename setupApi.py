from configuration import apiKey, apiRedirectUri, appSecret
from api import Api

api = Api(apiKey, apiRedirectUri, appSecret)

# Manual OAuth setup
api.setup()
