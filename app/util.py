from datetime import datetime

def get_logger(scope: str = None):
    import logging
    return logging.getLogger('morocco').getChild(scope) if scope else logging.getLogger('morocco')


def get_command_string(*args):
    return "/bin/bash -c 'set -e; set -o pipefail; {}; wait'".format(';'.join(args))


def generate_build_id():
    from datetime import datetime

    timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
    return 'build-{}'.format(timestamp)


def get_time_str(datetime: datetime) -> str:
    return datetime.strftime('%Y-%m-%d %H:%M:%S UTC')
