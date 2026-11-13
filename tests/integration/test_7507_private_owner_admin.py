"""#7507: the owner of a private project is created with the project admin role on top of editor/viewer (AC-1),
and ``get_private_project_owner`` names the owner only when name, owner_id and membership agree (AC-9, AC-3)."""
import importlib.util
import pathlib
import sys
import types

import pytest

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGE = "fakeprojects7507"


class FakeProject:
    def __init__(self, id_, name, owner_id):
        self.id, self.name, self.owner_id = id_, name, owner_id


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def where(self, *conditions):
        rows = self.rows
        for condition in conditions:
            rows = [row for row in rows if condition(row)]
        return FakeQuery(rows)

    def first(self):
        return self.rows[0] if self.rows else None


class FakeColumn:
    def __init__(self, name):
        self.name = name

    def __eq__(self, other):
        return lambda row: getattr(row, self.name) == other


class FakeSession:
    def __init__(self, projects):
        self.projects = projects

    def query(self, _model):
        return FakeQuery(self.projects)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _package(monkeypatch, name, path):
    package = types.ModuleType(name)
    package.__path__ = [str(path)]
    monkeypatch.setitem(sys.modules, name, package)


def _stub(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def poc(monkeypatch):
    state = types.SimpleNamespace(projects=[], members=set(), created=[])
    tools = _stub(
        monkeypatch, "tools",
        auth=types.SimpleNamespace(), rpc_tools=types.SimpleNamespace(wrap_exceptions=lambda *_: (lambda f: f)),
        db=types.SimpleNamespace(with_project_schema_session=lambda _pid: FakeSession(state.projects)),
        context=types.SimpleNamespace(), this=types.SimpleNamespace(module=types.SimpleNamespace(
            user_projects_cache={}, project_kind_cache={})),
    )
    _ = tools
    _stub(monkeypatch, "pylon")
    _stub(monkeypatch, "pylon.core")
    _stub(monkeypatch, "pylon.core.tools", web=types.SimpleNamespace(rpc=lambda *a, **k: (lambda f: f)),
          log=types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None,
                                    error=lambda *a, **k: None, critical=lambda *a, **k: None,
                                    exception=lambda *a, **k: None))
    _stub(monkeypatch, "cachetools", cached=lambda **_: (lambda f: f))
    _stub(monkeypatch, "pydantic")
    _stub(monkeypatch, "pydantic.v1", ValidationError=type("ValidationError", (Exception,), {}))
    for name, path in ((PACKAGE, PLUGIN_ROOT), (f"{PACKAGE}.rpc", PLUGIN_ROOT / "rpc"),
                       (f"{PACKAGE}.api", PLUGIN_ROOT / "api"), (f"{PACKAGE}.api.v2", PLUGIN_ROOT / "api" / "v2"),
                       (f"{PACKAGE}.models", PLUGIN_ROOT / "models"),
                       (f"{PACKAGE}.models.pd", PLUGIN_ROOT / "models" / "pd"),
                       (f"{PACKAGE}.utils", PLUGIN_ROOT / "utils")):
        _package(monkeypatch, name, path)
    _stub(monkeypatch, f"{PACKAGE}.api.v2.project", delete_project=lambda *a, **k: None)
    _stub(monkeypatch, f"{PACKAGE}.models.project", Project=types.SimpleNamespace(
        id=FakeColumn("id"), name=FakeColumn("name"), owner_id=FakeColumn("owner_id")))
    _stub(monkeypatch, f"{PACKAGE}.models.pd.project",
          ProjectCreatePD=lambda **kwargs: types.SimpleNamespace(**kwargs))
    _stub(monkeypatch, f"{PACKAGE}.utils.project_steps",
          create_project=lambda module, context: state.created.append(context))
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.constants", PLUGIN_ROOT / "constants.py")
    constants = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, constants)
    spec.loader.exec_module(constants)
    spec = importlib.util.spec_from_file_location(f"{PACKAGE}.rpc.poc", PLUGIN_ROOT / "rpc" / "poc.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    #
    rpc_call = types.SimpleNamespace(
        auth_get_user=lambda user_id: {"email": f"user{user_id}@example.com"},
        admin_check_user_in_project=lambda project_id, user_id: (project_id, user_id) in state.members,
    )
    instance = types.SimpleNamespace(context=types.SimpleNamespace(rpc_manager=types.SimpleNamespace(
        call=rpc_call, timeout=lambda _t: rpc_call)))
    instance.get_private_project_owner = types.MethodType(module.RPC.get_private_project_owner, instance)
    return module, instance, state


def test_new_private_project_owner_gets_admin_editor_viewer(poc):
    module, instance, state = poc

    assert module.create_personal_project(user_id=6, module=instance) is True

    assert len(state.created) == 1
    assert sorted(state.created[0]["roles"]) == ["admin", "editor", "viewer"]
    assert state.created[0]["owner_id"] == 6
    assert state.created[0]["project_model"].project_admin_email == "user6@example.com"


def test_verified_owner_is_returned(poc):
    _, instance, state = poc
    state.projects.append(FakeProject(4, "project_user_6", 6))
    state.members.add((4, 6))

    assert instance.get_private_project_owner(4) == 6


@pytest.mark.parametrize("project, members", [
    (FakeProject(4, "project_user_6", 3), {(4, 6)}),       # owner_id disagrees with the name
    (FakeProject(4, "project_user_6", 6), set()),          # owner is not a member
    (FakeProject(4, "Team Project", 6), {(4, 6)}),         # not a private project
    (FakeProject(4, "project_user_abc", 6), {(4, 6)}),     # unparsable owner id
])
def test_unverified_owner_is_none(poc, project, members):
    _, instance, state = poc
    state.projects.append(project)
    state.members.update(members)

    assert instance.get_private_project_owner(4) is None


def test_missing_project_is_none(poc):
    _, instance, _ = poc

    assert instance.get_private_project_owner(99) is None


def test_owner_not_yet_a_member_is_returned_when_membership_not_required(poc):
    _, instance, state = poc
    state.projects.append(FakeProject(4, "project_user_6", 6))

    assert instance.get_private_project_owner(4) is None
    assert instance.get_private_project_owner(4, require_member=False) == 6


def test_name_owner_mismatch_is_none_even_without_membership(poc):
    _, instance, state = poc
    state.projects.append(FakeProject(4, "project_user_6", 3))

    assert instance.get_private_project_owner(4, require_member=False) is None
