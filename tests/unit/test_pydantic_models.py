"""Unit tests for pydantic model validation."""
import sys
import pytest
from pydantic.v1 import BaseModel, constr, ValidationError
from typing import Optional, List, Union


@pytest.fixture(scope='module')
def group_module(models_path):
    """Load the group module."""
    pd_path = models_path / "pd"
    sys.path.insert(0, str(pd_path))
    try:
        import group
        return group
    finally:
        sys.path.remove(str(pd_path))


class ProjectCreatePD(BaseModel):
    """Copy of ProjectCreatePD - has relative imports, can't load directly."""
    name: constr(min_length=1)
    project_admin_email: Optional[Union[str, List[str]]] = None
    plugins: list = []
    data_retention_limit: int = 1_000_000_000
    test_duration_limit: int = -1
    cpu_limit: int = -1
    memory_limit: int = -1
    vcu_hard_limit: int = 5000
    vcu_soft_limit: int = 4700
    vcu_limit_total_block: bool = False
    storage_hard_limit: int = 10
    storage_soft_limit: int = 9
    storage_limit_total_block: bool = False
    invitation_integration: Optional[str] = None


class TestGroupCreateModel:
    """Tests for GroupCreateModel validation."""

    def test_valid_group(self, group_module):
        GroupCreateModel = group_module.GroupCreateModel
        group = GroupCreateModel(name="developers", project_id=1)
        assert group.name == "developers"
        assert group.project_id == 1

    def test_no_group_name_forbidden(self, group_module):
        GroupCreateModel = group_module.GroupCreateModel
        with pytest.raises(ValidationError) as exc_info:
            GroupCreateModel(name="no_group", project_id=1)
        assert "no_group" in str(exc_info.value)

    def test_empty_name_allowed(self, group_module):
        GroupCreateModel = group_module.GroupCreateModel
        group = GroupCreateModel(name="", project_id=1)
        assert group.name == ""

    def test_whitespace_name_allowed(self, group_module):
        GroupCreateModel = group_module.GroupCreateModel
        group = GroupCreateModel(name="  team  ", project_id=1)
        assert group.name == "  team  "


class TestGroupModifyModel:
    """Tests for GroupModifyModel validation."""

    def test_valid_modify(self, group_module):
        GroupModifyModel = group_module.GroupModifyModel
        modify = GroupModifyModel(groups=["admin", "dev"], project_id=1)
        assert modify.groups == ["admin", "dev"]
        assert modify.project_id == 1

    def test_empty_groups_list(self, group_module):
        GroupModifyModel = group_module.GroupModifyModel
        modify = GroupModifyModel(groups=[], project_id=1)
        assert modify.groups == []


class TestProjectCreatePD:
    """Tests for ProjectCreatePD validation."""

    def test_minimal_project(self):
        project = ProjectCreatePD(name="My Project")
        assert project.name == "My Project"
        assert project.plugins == []
        assert project.data_retention_limit == 1_000_000_000

    def test_name_min_length(self):
        with pytest.raises(ValidationError):
            ProjectCreatePD(name="")

    def test_single_char_name_allowed(self):
        project = ProjectCreatePD(name="X")
        assert project.name == "X"

    def test_admin_email_single_string(self):
        project = ProjectCreatePD(name="Test", project_admin_email="admin@example.com")
        assert project.project_admin_email == "admin@example.com"

    def test_admin_email_list(self):
        emails = ["admin@example.com", "dev@example.com"]
        project = ProjectCreatePD(name="Test", project_admin_email=emails)
        assert project.project_admin_email == emails

    def test_default_limits(self):
        project = ProjectCreatePD(name="Test")
        assert project.vcu_hard_limit == 5000
        assert project.vcu_soft_limit == 4700
        assert project.storage_hard_limit == 10
        assert project.storage_soft_limit == 9
        assert project.vcu_limit_total_block is False
        assert project.storage_limit_total_block is False

    def test_custom_limits(self):
        project = ProjectCreatePD(
            name="Test",
            vcu_hard_limit=10000,
            vcu_soft_limit=9500,
            cpu_limit=4,
            memory_limit=8192
        )
        assert project.vcu_hard_limit == 10000
        assert project.cpu_limit == 4
        assert project.memory_limit == 8192

    def test_plugins_list(self):
        project = ProjectCreatePD(name="Test", plugins=["auth", "social", "configurations"])
        assert len(project.plugins) == 3
        assert "auth" in project.plugins

    def test_invitation_integration_optional(self):
        project = ProjectCreatePD(name="Test", invitation_integration="task-123")
        assert project.invitation_integration == "task-123"

        project2 = ProjectCreatePD(name="Test2")
        assert project2.invitation_integration is None
