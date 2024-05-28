from api import Api
from configuration import apiKey, apiRedirectUri, appSecret

api = Api(apiKey, apiRedirectUri, appSecret)

# Manual OAuth setup
api.setup()
