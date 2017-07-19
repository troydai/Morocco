class SecretError(ValueError):
    def __init__(self):
        super(SecretError, self).__init__('Invalid secret')
