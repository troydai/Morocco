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
