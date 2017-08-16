from typing import Iterable
from .models import DbBuild, DbTestCase, DbTestRun


class ViewModel(object):
    def __getattr__(self, name):
        if hasattr(self.data, name):
            return getattr(self.data, name)
        raise AttributeError(f'Attribute {name} is not found.')


class TestCase(ViewModel):
    def __init__(self, test_case: DbTestCase):
        super(TestCase, self).__init__()
        self.data = test_case


class TestRun(ViewModel):
    def __init__(self, test_run: DbTestRun):
        super(TestRun, self).__init__()
        self.data = test_run


class Snapshot(ViewModel):
    def __init__(self, build: DbBuild):
        super(Snapshot, self).__init__()
        self.data = build
        self._last_live_test_run = None
        self._last_live_test_run_attempted = False

    @property
    def commit_sha(self):
        return self.data.id

    @property
    def commit_sha_short(self):
        return self.data.id[:6]

    @property
    def commit_date(self):
        return self.data.commit_date.strftime('%b %d, %Y') if self.data.commit_date else 'N/A'

    @property
    def commit_subject(self):
        return self.data.commit_message.strip().split('\n')[0] if self.data.commit_message else 'N/A'

    @property
    def last_live_test_run(self):
        from .models import DbTestRun
        if not self._last_live_test_run and not self._last_live_test_run_attempted:
            self._last_live_test_run_attempted = True
            self._last_live_test_run = DbTestRun.query.filter_by(build_id=self.data.id).filter_by(live=True).order_by(
                DbTestRun.creation_time.desc()).first()

        return self._last_live_test_run

    @property
    def live_test_pass_rate(self):
        return f'{self.last_live_test_run.get_pass_percentage()}%' if self.last_live_test_run else ''

    @property
    def live_test_failed_cases(self) -> Iterable[TestCase]:
        if not self.last_live_test_run:
            return []

        failed_test_cases = DbTestCase.query.filter_by(test_run_id=self.last_live_test_run.id).filter_by(
            passed=False).all()
        return (TestCase(t) for t in failed_test_cases)

    @property
    def test_runs(self) -> Iterable[TestRun]:
        if self.data.tests.count() > 0:
            return (TestRun(r) for r in self.data.tests)
        else:
            return []
