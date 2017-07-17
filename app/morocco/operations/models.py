from azure.batch.models import CloudJob
from morocco.util import get_time_str


class BasicJobView(object):
    def __init__(self, job: CloudJob):
        self.job = job

    @property
    def id(self):  # pylint: disable=invalid-name
        return self.job.id

    @property
    def start_time(self):
        return get_time_str(self.job.execution_info.start_time)

    @property
    def end_time(self):
        return get_time_str(self.job.execution_info.end_time) if self.job.execution_info.end_time else 'N/A'

    @property
    def state(self):
        return self.job.state.value
