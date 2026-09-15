"""Regression tests for the project system-token step under elitea_issues#5262.

auth_core now gives every user a non-expiring token named 'elitea-system', and
auth.list_tokens hides it unless the caller opts in. SystemToken.create decides
whether to mint a token by looking at how many tokens the project system user
already has, so it is one of the call sites that default is protecting: if the
hidden token ever became visible here, `all_tokens[0]` could hand the project's
system token slot to a token the platform refuses to delete or rotate, and
`get_system_user_token(name='api')` would then never find a match.

These tests load the real module rather than a copy so they fail if someone
later passes include_system=True or reorders the branch.
"""
import importlib.util
import pathlib
import sys
import types

import pytest

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
PKG = 'projects_pkg_5262'


class AuthDouble:
    """Records calls and mimics auth_core's post-#5262 list_tokens contract."""

    def __init__(self, visible_tokens=None):
        self.visible_tokens = visible_tokens or []
        self.list_calls = []
        self.add_calls = []
        self.deleted = []

    def list_tokens(self, *args, **kwargs):
        self.list_calls.append((args, kwargs))
        return list(self.visible_tokens)

    def add_token(self, *args, **kwargs):
        self.add_calls.append((args, kwargs))
        return 999

    def delete_token(self, token_id=None, **kwargs):
        self.deleted.append(token_id)

    def encode_token(self, token_id):
        return f'encoded-{token_id}'


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


def _system_token_step(project_steps, auth_double):
    project_steps.auth = auth_double
    return project_steps.SystemToken(module=None)


def test_mints_api_token_when_user_only_has_the_hidden_system_token(project_steps):
    """add_user provisions the system token, but list_tokens hides it, so the step
    still sees an empty list and mints the 'api' token the project needs."""
    auth_double = AuthDouble(visible_tokens=[])
    step = _system_token_step(project_steps, auth_double)

    result = step.create(system_user_id=42)

    assert auth_double.add_calls == [((42, 'api'), {})]
    assert result == {'system_token': 'encoded-999'}


def test_does_not_opt_into_seeing_system_tokens(project_steps):
    """The guard: this call site must never pass include_system=True."""
    auth_double = AuthDouble(visible_tokens=[])
    step = _system_token_step(project_steps, auth_double)

    step.create(system_user_id=42)

    (args, kwargs), = auth_double.list_calls
    assert 'include_system' not in kwargs
    assert True not in args[1:]


def test_reuses_an_existing_api_token(project_steps):
    auth_double = AuthDouble(visible_tokens=[{'id': 7, 'name': 'api'}])
    step = _system_token_step(project_steps, auth_double)

    result = step.create(system_user_id=42)

    assert auth_double.add_calls == []
    assert result == {'system_token': 'encoded-7'}


def test_delete_only_touches_visible_tokens(project_steps):
    """The hidden system token is left to the ON DELETE CASCADE from delete_user;
    delete_token would refuse it anyway."""
    auth_double = AuthDouble(visible_tokens=[{'id': 7, 'name': 'api'}, {'id': 8, 'name': 'other'}])
    step = _system_token_step(project_steps, auth_double)

    step.delete(system_user_id=42)

    assert auth_double.deleted == [7, 8]


def test_delete_is_a_noop_without_a_system_user(project_steps):
    auth_double = AuthDouble(visible_tokens=[{'id': 7, 'name': 'api'}])
    step = _system_token_step(project_steps, auth_double)

    step.delete()

    assert auth_double.deleted == []
