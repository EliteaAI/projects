"""#7490: project_get_created_at returns the project's creation time from its statistic row.

The statistic row is written together with the project and start_time is naive UTC, so the value is
returned as ISO 8601 with an explicit UTC offset. A project without a row has no creation time.
"""
import ast
import contextlib
import datetime
import pathlib
import types

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session, declarative_base

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
RPC_MAIN = PLUGIN_ROOT / "rpc" / "main.py"

Base = declarative_base()


class Statistic(Base):
    __tablename__ = "statistic"
    id = sa.Column(sa.Integer, primary_key=True)
    project_id = sa.Column(sa.Integer, nullable=False)
    start_time = sa.Column(sa.DateTime)


def _function(path, class_name, func_name):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    func = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == func_name)
    func.decorator_list = []
    return func


@pytest.fixture
def engine():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def get_created_at(engine):
    @contextlib.contextmanager
    def get_session():
        with Session(engine) as session:
            yield session

    namespace = {
        "Optional": __import__("typing").Optional,
        "Statistic": Statistic,
        "db": types.SimpleNamespace(get_session=get_session),
        "timezone": datetime.timezone,
    }
    func = _function(RPC_MAIN, "RPC", "get_created_at")
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(RPC_MAIN), "exec"), namespace)  # pylint: disable=W0122
    return lambda project_id: namespace["get_created_at"](None, project_id)


def add_statistic(engine, project_id, start_time, id_=None):
    with Session(engine) as session:
        session.add(Statistic(id=id_, project_id=project_id, start_time=start_time))
        session.commit()


def test_returns_the_start_time_as_utc_iso(engine, get_created_at):
    add_statistic(engine, 10, datetime.datetime(2026, 7, 13, 9, 18, 11, 904953))

    assert get_created_at(10) == "2026-07-13T09:18:11.904953+00:00"


def test_a_project_without_a_statistic_row_has_no_creation_time(engine, get_created_at):
    add_statistic(engine, 10, datetime.datetime(2026, 7, 13, 9, 18, 11))

    assert get_created_at(11) is None


def test_a_row_without_start_time_has_no_creation_time(engine, get_created_at):
    add_statistic(engine, 10, None)

    assert get_created_at(10) is None


def test_the_earliest_row_wins_if_there_are_several(engine, get_created_at):
    add_statistic(engine, 10, datetime.datetime(2026, 1, 20, 11, 7, 19), id_=1)
    add_statistic(engine, 10, datetime.datetime(2026, 5, 5, 10, 14, 47), id_=2)

    assert get_created_at(10) == "2026-01-20T11:07:19+00:00"
