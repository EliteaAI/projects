"""#5202: PUT/DELETE of a project ask the admin plugin (same pylon) whether SCIM manages it.

No admin plugin, or SCIM provisioning off -> nothing is protected (no deploy-order coupling).
A protected project -> 403. A failing check -> 503 (fail closed)."""
import ast
import pathlib
import types

import pytest

SOURCE = pathlib.Path(__file__).resolve().parents[2] / "api" / "v2" / "project.py"


def _load_refusal():
    """ Only _scim_refusal and its constants: the rest of project.py needs a running pylon """
    tree = ast.parse(SOURCE.read_text())
    wanted = [node for node in tree.body if (
        isinstance(node, ast.FunctionDef) and node.name.startswith("_scim")
    ) or (
        isinstance(node, ast.Assign) and any(getattr(t, "id", "").startswith("SCIM_") for t in node.targets)
    )]
    namespace = {"log": types.SimpleNamespace(exception=lambda *a, **k: None)}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(SOURCE), "exec"), namespace)  # pylint: disable=W0122
    return namespace["_scim_refusal"]


def module_with(admin_module):
    modules = {} if admin_module is None else {"admin": types.SimpleNamespace(module=admin_module)}
    return types.SimpleNamespace(context=types.SimpleNamespace(module_manager=types.SimpleNamespace(modules=modules)))


@pytest.fixture
def refusal():
    return _load_refusal()


def guards(protected=(), error=None):
    def is_protected(project_id):
        if error:
            raise error
        return project_id in protected
    return types.SimpleNamespace(scim=types.SimpleNamespace(guards=types.SimpleNamespace(is_protected=is_protected)))


def test_no_admin_plugin_means_not_protected(refusal):
    assert refusal(module_with(None), 7) is None


def test_scim_disabled_means_not_protected(refusal):
    assert refusal(module_with(types.SimpleNamespace(scim=None)), 7) is None


def test_protected_project_is_403(refusal):
    body, status = refusal(module_with(guards(protected={7})), 7)
    assert status == 403 and "SCIM" in body["message"]


def test_unprotected_project_passes(refusal):
    assert refusal(module_with(guards(protected={7})), 3) is None


def test_failing_check_is_503(refusal):
    body, status = refusal(module_with(guards(error=RuntimeError("db down"))), 7)
    assert status == 503
