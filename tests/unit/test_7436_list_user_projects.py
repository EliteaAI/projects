"""#7436: list_user_projects resolves the user's project ids first, then loads only those projects.

Paging, search and the suspended filter apply to the user's own projects, so limit=5 returns up to five
of the user's projects instead of whichever of the first five platform projects they belong to.
The project table is an in-memory stand-in; the real query is exercised by the 16k-project scale run.
"""
import ast
import pathlib
import types

import pytest

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
POC = PLUGIN_ROOT / "rpc" / "poc.py"
PROJECT_MODEL = PLUGIN_ROOT / "models" / "project.py"
USER, OTHER = 3, 6
# id, name, suspended, owner
ROWS = [(1, "alpha", False), (2, "beta", False), (3, "alpine", True), (4, "gamma", False),
        (5, "alphabet", False), (6, "delta", False), (7, "alpha two", False), (8, "zeta", False)]
MEMBERS = {USER: [2, 3, 4, 5, 7, 8], OTHER: [1]}


def _function(path, class_name, func_name):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    func = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == func_name)
    func.decorator_list = [d for d in func.decorator_list if getattr(d, "id", "") == "staticmethod"]
    return func


@pytest.fixture
def listing(monkeypatch):
    """list_projects with the DB layer replaced by an in-memory table that honours ids/filter/search/limit/offset."""
    calls = []

    def fake_list(**kwargs):
        calls.append(kwargs)
        ids, search = kwargs.get("ids_"), kwargs.get("search_")
        flt = kwargs.get("filter_") or {}
        rows = [r for r in ROWS if (ids is None or r[0] in ids)
                and (search is None or search.lower() in r[1])
                and all({"suspended": r[2]}.get(k) == v for k, v in flt.items())]
        start = int(kwargs.get("offset_") or 0)
        stop = None if kwargs.get("limit_") is None else start + int(kwargs["limit_"])
        return [{"id": r[0], "name": r[1], "suspended": r[2]} for r in rows[start:stop]]

    rpc_calls = []

    def project_ids(user_id):
        rpc_calls.append(user_id)
        return MEMBERS.get(user_id, [])

    func = _function(POC, "RPC", "list_user_projects")
    namespace = {}
    exec(compile(ast.Module(body=[func], type_ignores=[]), str(POC), "exec"), namespace)  # pylint: disable=W0122
    subject = types.SimpleNamespace(
        list=fake_list,
        context=types.SimpleNamespace(rpc_manager=types.SimpleNamespace(
            call=types.SimpleNamespace(admin_list_user_project_ids=project_ids))),
    )
    return types.SimpleNamespace(run=lambda *a, **k: namespace["list_user_projects"](subject, *a, **k),
                                 calls=calls, rpc_calls=rpc_calls)


def ids(projects):
    return [p["id"] for p in projects]


def test_7436_returns_only_the_users_projects_without_suspended_ones(listing):
    assert ids(listing.run(USER)) == [2, 4, 5, 7, 8]


def test_7436_include_suspended_keeps_the_suspended_project(listing):
    assert ids(listing.run(USER, include_suspended=True)) == [2, 3, 4, 5, 7, 8]


def test_7436_user_with_no_projects_never_touches_the_project_table(listing):
    assert listing.run(99) == []
    assert listing.calls == []


def test_7436_limit_and_offset_page_through_the_users_own_projects(listing):
    # Before the fix limit_=2 cut the platform list to ids 1-2 and returned only beta (id 2)
    assert ids(listing.run(USER, limit_="2")) == [2, 4]
    assert ids(listing.run(USER, limit_="2", offset_="2")) == [5, 7]


def test_7436_search_applies_to_the_users_projects_only(listing):
    assert ids(listing.run(USER, search_="alp")) == [5, 7]


def test_7436_the_full_project_table_is_never_requested_without_ids(listing):
    listing.run(USER)
    assert all(call.get("ids_") for call in listing.calls)


def test_7436_a_caller_cannot_smuggle_a_foreign_ids_filter(listing):
    assert ids(listing.run(USER, ids_=[1])) == [2, 4, 5, 7, 8]


def test_7436_list_projects_builds_one_where_for_ids_search_and_filter():
    source = PROJECT_MODEL.read_text()
    assert "Project.id.in_(ids_)" in source
    assert "elif search_" not in source
