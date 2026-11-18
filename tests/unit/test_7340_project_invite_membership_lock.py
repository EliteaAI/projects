"""#7340: concurrent manual invitations recheck membership while holding the project row lock."""
import ast
import contextlib
import pathlib
import types

import pytest


PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
POC = PLUGIN_ROOT / "rpc" / "poc.py"
AUDIT_CTX = {"actor_type": "user", "actor_id": 42}


def _function():
    tree = ast.parse(POC.read_text())
    rpc_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "RPC")
    function = next(
        node for node in rpc_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "add_user_to_project_or_create"
    )
    function.decorator_list = []
    return function


@pytest.fixture
def invite_rpc():
    call_order = []
    project_members = set()

    class Query:
        def filter(self, *_args):
            return self

        def with_for_update(self):
            call_order.append("lock")
            return self

        def first(self):
            return (10,)

    class Session:
        def query(self, *_args):
            return Query()

    @contextlib.contextmanager
    def with_project_schema_session(_project_id):
        yield Session()

    user = {"id": 7, "email": "Alice@example.com"}
    auth = types.SimpleNamespace(
        list_users=lambda: [user],
        add_user=lambda _email: pytest.fail("Existing identity should not be recreated"),
    )

    def get_members(project_id):
        call_order.append("check")
        return list(project_members)

    def add_member(project_id, user_id, roles, *, audit_ctx):
        assert audit_ctx == AUDIT_CTX
        call_order.append(("add", project_id, user_id, roles))
        project_members.add(user_id)

    rpc = types.SimpleNamespace(
        admin_get_users_ids_in_project=get_members,
        admin_add_user_to_project=add_member,
    )
    subject = types.SimpleNamespace(context=types.SimpleNamespace(
        rpc_manager=types.SimpleNamespace(call=rpc),
    ))
    namespace = {
        "Project": types.SimpleNamespace(id=object()),
        "auth": auth,
        "audit_ctx_or_current": lambda ctx: ctx,
        "db": types.SimpleNamespace(with_project_schema_session=with_project_schema_session),
        "log": types.SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None),
        "create_keycloak_user": lambda *_a, **_k: None,
    }
    exec(compile(ast.Module(body=[_function()], type_ignores=[]), str(POC), "exec"), namespace)  # pylint: disable=W0122
    return types.SimpleNamespace(
        run=lambda email, roles: namespace["add_user_to_project_or_create"](
            subject, email, 10, roles, audit_ctx=AUDIT_CTX,
        ),
        call_order=call_order,
        project_members=project_members,
    )


@pytest.mark.parametrize("second_roles", [["viewer"], ["admin"]])
def test_competing_invites_recheck_membership_under_the_project_lock(invite_rpc, second_roles):
    first = invite_rpc.run("ALICE@EXAMPLE.COM", ["viewer"])
    second = invite_rpc.run("alice@example.com", second_roles)

    assert first["status"] == "ok"
    assert second["status"] == "error"
    assert invite_rpc.call_order == [
        "lock",
        "check",
        ("add", 10, 7, ["viewer"]),
        "lock",
        "check",
    ]


def test_user_creation_collision_resolves_the_canonical_identity():
    call_order = []

    def raise_unique_email_collision():
        raise RuntimeError("unique email collision")

    def create_user(_email, *, audit_ctx):
        assert audit_ctx == AUDIT_CTX
        raise_unique_email_collision()

    def add_member(project_id, user_id, roles, *, audit_ctx):
        assert audit_ctx == AUDIT_CTX
        call_order.append(("add", project_id, user_id, roles))

    class Query:
        def filter(self, *_args):
            return self

        def with_for_update(self):
            call_order.append("lock")
            return self

        def first(self):
            return (10,)

    class Session:
        def query(self, *_args):
            return Query()

    @contextlib.contextmanager
    def with_project_schema_session(_project_id):
        yield Session()

    auth = types.SimpleNamespace(
        list_users=lambda: [],
        add_user=create_user,
        get_user=lambda email: {"id": 23, "email": email},
        add_user_provider=lambda *_a: pytest.fail("Raced identity must not be re-created"),
        add_user_group=lambda *_a: pytest.fail("Raced identity must not be re-created"),
    )
    rpc = types.SimpleNamespace(
        admin_get_users_ids_in_project=lambda _project_id: [],
        admin_add_user_to_project=add_member,
    )
    subject = types.SimpleNamespace(context=types.SimpleNamespace(
        rpc_manager=types.SimpleNamespace(call=rpc),
    ))
    namespace = {
        "Project": types.SimpleNamespace(id=object()),
        "auth": auth,
        "audit_ctx_or_current": lambda ctx: ctx,
        "db": types.SimpleNamespace(with_project_schema_session=with_project_schema_session),
        "log": types.SimpleNamespace(info=lambda *_a, **_k: None, warning=lambda *_a, **_k: None,
                                     exception=lambda *_a, **_k: None),
        "create_keycloak_user": lambda *_a, **_k: None,
    }
    exec(compile(ast.Module(body=[_function()], type_ignores=[]), str(POC), "exec"), namespace)  # pylint: disable=W0122

    result = namespace["add_user_to_project_or_create"](
        subject, "NEW@example.com", 10, ["viewer"], audit_ctx=AUDIT_CTX,
    )

    assert result["status"] == "ok"
    assert result["id"] == 23
    assert call_order == ["lock", ("add", 10, 23, ["viewer"])]
