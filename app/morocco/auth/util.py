def validate_github_webhook(request, secret: str) -> bool:
    import hmac

    sig = request.headers.get('X-Hub-Signature')
    if not sig:
        return False

    scheme, sig = sig.split('=')
    if scheme != 'sha1':
        return False

    mac = hmac.new(secret.encode(), msg=request.data, digestmod='sha1')
    return hmac.compare_digest(str(mac.hexdigest()), str(sig))


def validate_batch_callback(request) -> bool:
    return True