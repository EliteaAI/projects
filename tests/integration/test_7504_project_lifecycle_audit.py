"""EL-7504: project lifecycle audit in the projects plugin (AC-2, AC-8, AC-9, AC-25).

create_project records project.created in its own session, so the event commits with the project and a
failed creation leaves none. The project's system user is created and removed with a System audit context.
"""
import importlib.util
import pathlib
import sys
import types

import pytest

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = 'projects_pkg_7504'


def _stub(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


@pytest.fixture
def project_steps():
    """Load utils/project_steps.py for real, with its plugin-internal imports stubbed."""
    original = dict(sys.modules)

    # run_tests.py installs the pylon/tools stubs before handing control to pytest.
    tools = sys.modules['tools']
    tools.VaultClient = object
    tools.MinioClient = object
    tools.constants = types.SimpleNamespace(DEFAULT_MODE='default')
    tools.auth = None  # replaced per-test below
    tools.this = types.SimpleNamespace(for_module=lambda name: None)  # #7504 audit writer lookup
    tools.db = types.SimpleNamespace()

    class ProjectCreationStep:
        all_steps = []

        def __init__(self, module=None):
            self.module = module

    root = _stub(PKG)
    root.__path__ = [str(PLUGIN_ROOT)]
    utils = _stub(f'{PKG}.utils', get_project_user=lambda project_id: {'id': 1})
    utils.__path__ = [str(PLUGIN_ROOT / 'utils')]
    root.utils = utils

    _stub(f'{PKG}.utils.helpers', ProjectCreationStep=ProjectCreationStep)
    _stub(
        f'{PKG}.utils.rabbit_utils',
        password_generator=lambda *a, **k: 'pw',
        create_rabbit_user_and_vhost=lambda *a, **k: None,
        delete_rabbit_user_and_vhost=lambda *a, **k: None,
    )
    _stub(
        f'{PKG}.constants',
        INFLUX_DATABASES=[],
        PROJECT_SCHEMA_TEMPLATE='p_{}',
        PROJECT_USER_NAME_TEMPLATE='project-{}',
        PROJECT_USER_EMAIL_TEMPLATE='project-{}@centry.user',
        PROJECT_RABBIT_USER_TEMPLATE='rabbit-{}',
        PROJECT_RABBIT_VHOST_TEMPLATE='vhost-{}',
    )
    models = _stub(f'{PKG}.models')
    models.__path__ = [str(PLUGIN_ROOT / 'models')]
    pd_pkg = _stub(f'{PKG}.models.pd')
    pd_pkg.__path__ = [str(PLUGIN_ROOT / 'models' / 'pd')]
    _stub(f'{PKG}.models.pd.project', ProjectCreatePD=object)
    _stub(f'{PKG}.models.project', Project=object)
    _stub(f'{PKG}.models.quota', ProjectQuota=object)
    _stub(f'{PKG}.models.statistics', Statistic=object)
    plugin_tools = _stub(f'{PKG}.tools')
    plugin_tools.__path__ = [str(PLUGIN_ROOT / 'tools')]
    _stub(f'{PKG}.tools.influx_tools', get_client=lambda *a, **k: None)

    name = f'{PKG}.utils.project_steps'
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN_ROOT / 'utils' / 'project_steps.py',
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)

    yield module

    for key in [k for k in sys.modules if k not in original]:
        del sys.modules[key]




class Session:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class AdminModule:
    """The admin plugin's writer as projects reaches it: this.for_module('admin').module"""

    def __init__(self):
        self.recorded = []

    def lifecycle_audit_record(self, session, events):
        self.recorded.append((session, events))

    def lifecycle_audit_ctx(self, executing_user_id=None):
        return {"actor_type": "user", "actor_id": 7, "actor_name": "Root", "actor_email": "r@x",
                "source": "ui", "request_id": None}


class FakeProject:
    def __init__(self, id_, name, owner_id):
        self.id, self.name, self.owner_id, self.create_success = id_, name, owner_id, False

    def to_json(self):
        return {"id": self.id, "name": self.name}


class Step:
    def __init__(self, project=None, fail=False):
        self.project, self.fail, self.name = project, fail, "step"
        self.deleted = False

    def create(self, **kwargs):
        if self.fail:
            raise RuntimeError("step failed")
        return {"project": self.project} if self.project else None

    def delete(self, **kwargs):
        self.deleted = True


ADMIN_EVENTS = PLUGIN_ROOT.parent / "admin" / "utils" / "lifecycle_audit" / "events.py"


@pytest.fixture
def admin_events(monkeypatch):
    """The real admin builder, where project_steps imports it from"""
    spec = importlib.util.spec_from_file_location("plugins.admin.utils.lifecycle_audit.events", ADMIN_EVENTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("plugins", "plugins.admin", "plugins.admin.utils"):
        package = sys.modules.get(name) or types.ModuleType(name)
        package.__path__ = []
        monkeypatch.setitem(sys.modules, name, package)
    package = types.ModuleType("plugins.admin.utils.lifecycle_audit")
    package.events = module
    monkeypatch.setitem(sys.modules, "plugins.admin.utils.lifecycle_audit", package)
    monkeypatch.setitem(sys.modules, spec.name, module)
    return module


@pytest.fixture
def env(project_steps, monkeypatch, admin_events):
    session = Session()
    admin = AdminModule()
    project_steps.db = types.SimpleNamespace(with_project_schema_session=lambda _pid: session)
    project_steps.this = types.SimpleNamespace(for_module=lambda name: types.SimpleNamespace(module=admin))
    module = types.SimpleNamespace(context=types.SimpleNamespace(
        event_manager=types.SimpleNamespace(fire_event=lambda *a: None)))
    return types.SimpleNamespace(steps=project_steps, session=session, admin=admin, module=module,
                                 monkeypatch=monkeypatch)


def run(env, steps, context):
    env.monkeypatch.setattr(env.steps, "get_steps", lambda module, reverse=False: iter(steps))
    return env.steps.create_project(env.module, context)


def test_team_project_created_with_owner_and_creator_kept_apart(env):
    project = FakeProject(5, "Alpha", owner_id=11)
    ctx = {"actor_type": "user", "actor_id": 7, "actor_name": "Root", "actor_email": "r@x",
           "source": "ui", "request_id": "r1"}

    run(env, [Step(project)], {"owner_id": 11, "audit_ctx": ctx})

    [(session, [event])] = env.admin.recorded
    assert session is env.session
    assert event["event_type"] == "project.created"
    assert event["project_id"] == 5 and event["project_name"] == "Alpha"
    assert event["project_type"] == "team"
    assert event["details"]["owner"]["id"] == 11
    assert event["details"]["creator"]["id"] == 7
    assert event["actor_id"] == 7


def test_private_project_created_by_system_for_its_owner(env):
    project = FakeProject(6, "project_user_11", owner_id=11)

    run(env, [Step(project)], {"owner_id": 11, "audit_ctx": env.steps.SYSTEM_AUDIT_CTX})

    [(_, [event])] = env.admin.recorded
    assert event["project_type"] == "private"
    assert event["actor_type"] == "system"
    assert event["details"]["creator"] == {"id": None, "name": "System"}
    assert event["details"]["owner"]["id"] == 11


def test_missing_ctx_uses_the_current_request(env):
    run(env, [Step(FakeProject(5, "Alpha", owner_id=11))], {"owner_id": 11})

    [(_, [event])] = env.admin.recorded
    assert event["source"] == "ui"


def test_failed_creation_records_nothing(env):
    with pytest.raises(env.steps.ProjectCreateError):
        run(env, [Step(FakeProject(5, "Alpha", owner_id=11)), Step(fail=True)], {"owner_id": 11})

    assert env.admin.recorded == []


def test_audit_record_is_written_before_the_final_commit(env):
    project = FakeProject(5, "Alpha", owner_id=11)
    seen = {}

    def record(session, events):
        seen["commits_before"] = session.commits
        seen["create_success"] = project.create_success

    env.admin.lifecycle_audit_record = record
    run(env, [Step(project)], {"owner_id": 11})

    assert seen == {"commits_before": 0, "create_success": True}
    assert env.session.commits == 1


class AuthRecorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            return 99
        return call


def test_system_user_is_created_and_removed_as_system(env):
    auth = AuthRecorder()
    env.steps.auth = auth
    env.steps.get_project_user = lambda project_id: (_ for _ in ()).throw(RuntimeError("none"))
    step = env.steps.SystemUser(module=None)

    step.create(project=FakeProject(5, "Alpha", 11))
    step.delete(system_user_id=99)

    assert [c[0] for c in auth.calls] == ["add_user", "assign_user_to_role", "delete_user"]
    assert all(c[2]["audit_ctx"]["actor_type"] == "system" for c in auth.calls)


# --- rename / delete / suspend (AC-2, AC-3, AC-11, AC-25) -----------------------------

def test_rename_records_old_and_new_name(env):
    project = FakeProject(5, "Alpha", owner_id=11)

    events = env.steps.rename_events(project, "Beta", env.admin.lifecycle_audit_ctx())

    [event] = events
    assert event["event_type"] == "project.renamed"
    assert event["changes"] == {"name": {"before": "Alpha", "after": "Beta"}}
    assert event["project_name"] == "Beta"


@pytest.mark.parametrize("new_name", ["Alpha", "", None])
def test_rename_without_change_records_nothing(env, new_name):
    assert env.steps.rename_events(FakeProject(5, "Alpha", 11), new_name, {}) == []


def test_delete_records_project_and_each_member_once(env):
    project = FakeProject(5, "project_user_11", owner_id=11)
    members = {11: ["admin", "editor"], 12: ["viewer"]}
    users = {11: {"id": 11, "name": "Ann", "email": "ann@x"}, 12: {"id": 12, "name": "Bob", "email": "bob@x"}}

    events = env.steps.delete_events(project, members, users, env.steps.SYSTEM_AUDIT_CTX)

    assert [e["event_type"] for e in events] == [
        "project.deleted", "project.member_removed", "project.member_removed",
    ]
    deleted, ann, bob = events
    assert deleted["project_name"] == "project_user_11"
    assert deleted["project_type"] == "private"
    assert deleted["details"]["owner"]["id"] == 11
    assert ann["user_email"] == "ann@x" and ann["roles_before"] == ["admin", "editor"]
    assert ann["roles_after"] == [] and ann["admin_access"] == "revoked"
    assert bob["details"]["reason"] == "project_deleted"
    assert not any(e["event_type"] == "user.deleted" for e in events)


@pytest.mark.parametrize("before, after, expected", [
    (False, True, ["project.suspended"]),
    (True, False, ["project.unsuspended"]),
    (True, True, []),
])
def test_suspend_events_only_on_change(env, before, after, expected):
    project = FakeProject(5, "Alpha", owner_id=11)
    project.suspended = before

    events = env.steps.suspend_events(project, after, env.steps.SYSTEM_AUDIT_CTX)

    assert [e["event_type"] for e in events] == expected


class QuerySession(Session):
    """Records the order of commits and the project row delete"""

    def __init__(self):
        super().__init__()
        self.log = []

    def query(self, _model):
        return types.SimpleNamespace(filter=lambda *_: types.SimpleNamespace(delete=lambda: None))

    def delete(self, _obj):
        self.log.append("delete project")

    def commit(self):
        super().commit()
        self.log.append("commit")


def test_delete_events_commit_with_the_project_row(env):
    session = QuerySession()
    env.admin.lifecycle_audit_record = lambda s, events: session.log.append("audit")
    env.steps.Statistic = env.steps.ProjectQuota = types.SimpleNamespace(project_id=None)

    env.steps.ProjectModel(module=None).delete(
        project=FakeProject(5, "Alpha", 11), session=session, audit_events=[{"event_type": "project.deleted"}],
    )

    assert session.log[-3:] == ["audit", "delete project", "commit"]
