from datetime import datetime
from logging import Logger


def get_logger(scope: str = None) -> Logger:
    import logging
    return logging.getLogger('morocco').getChild(scope) if scope else logging.getLogger('morocco')


def get_command_string(*args) -> str:
    return "/bin/bash -c 'set -e; set -o pipefail; {}; wait'".format(';'.join(args))


def generate_build_id() -> str:
    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    return 'build-{}'.format(timestamp)


def get_time_str(time: datetime) -> str:
    return time.strftime('%Y-%m-%d %H:%M:%S UTC')


def get_tenant_from_endpoint(endpoint: str) -> str:
    from urllib.parse import urlparse
    tenant, *_ = urlparse(endpoint)[2].split('/', 1)

    return tenant


def should_return_html(request) -> bool:
    """Poor man's content negotiation"""
    for each in request.headers.get('Accept').split(','):
        if each in ('text/html', 'application/xhtml+xml'):
            return True
    return False
