import pytest

from crmscore.service import build_lifecycle, load_demo_data


@pytest.fixture(scope="session")
def lc(tmp_path_factory):
    work = tmp_path_factory.mktemp("run")
    lifecycle = build_lifecycle(warehouse="duckdb", crm="mock", workdir=str(work))
    load_demo_data(lifecycle)
    lifecycle.bootstrap("lead")
    lifecycle.bootstrap("account")
    return lifecycle
