class ModelError(Exception):
    "Models can raise this error, which will be displayed to the user"
    pass


class NeedsKeyException(ModelError):
    "Model needs an API key which has not been provided"
    pass
