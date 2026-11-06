"""#5202 (AC-4): projects_scim_find_by_name gives the ids of the active team projects a SCIM group may be
linked to: name equal case-insensitively, personal and suspended projects left out."""
import importlib.util
import pathlib
import sys
import types
from contextlib import contextmanager

import pytest
from sqlalchemy import Boolean, Column, Integer, String, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
Base = declarative_base()


class Project(Base):
    __tablename__ = "project"
    id = Column(Integer, primary_key=True)
    name = Column(String(256), nullable=False)
    suspended = Column(Boolean, nullable=False, default=False)


@pytest.fixture
def find(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")
    Base.metadata.create_all(engine)
    make_session = sessionmaker(bind=engine)

    @contextmanager
    def get_session(_project_id):
        session = make_session()
        try:
            yield session
        finally:
            session.close()

    tools = types.ModuleType("tools")
    tools.db = types.SimpleNamespace(get_session=get_session)
    tools.rpc_tools = types.SimpleNamespace(wrap_exceptions=lambda exc: (lambda f: f))
    pylon_tools = types.ModuleType("pylon.core.tools")
    pylon_tools.web = types.SimpleNamespace(rpc=lambda *a, **k: (lambda f: f))
    pylon_tools.log = types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None)
    stubs = {"tools": tools, "pylon": types.ModuleType("pylon"), "pylon.core": types.ModuleType("pylon.core"),
             "pylon.core.tools": pylon_tools}
    for name in ("fake5202projects", "fake5202projects.rpc", "fake5202projects.models",
                 "fake5202projects.models.pd", "fake5202projects.utils"):
        package = types.ModuleType(name)
        package.__path__ = []
        stubs[name] = package
    stubs["fake5202projects.models.project"] = types.SimpleNamespace(Project=Project)
    stubs["fake5202projects.models.pd.project"] = types.SimpleNamespace(ProjectCreatePD=dict)
    stubs["fake5202projects.utils.project_steps"] = types.SimpleNamespace(create_project=None)
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location("fake5202projects.rpc.scim", PLUGIN_ROOT / "rpc" / "scim.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    with get_session(None) as session:
        session.add_all([
            Project(id=1, name="Finance", suspended=False),
            Project(id=2, name="FINANCE", suspended=False),
            Project(id=3, name="finance", suspended=True),
            Project(id=4, name="Finance team", suspended=False),
            Project(id=5, name="project_user_9", suspended=False),
        ])
        session.commit()
    return lambda name: module.RPC.projects_scim_find_by_name(None, name)


def test_matches_active_team_projects_case_insensitively(find):
    assert find("finance") == [1, 2]
    assert find("  Finance ") == [1, 2]


def test_personal_and_unknown_names_match_nothing(find):
    assert find("project_user_9") == []
    assert find("Marketing") == []
