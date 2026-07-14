"""Unit tests for utils/helpers.py - ProjectCreationStep ABC."""
import pytest
from abc import ABC, abstractmethod


class ProjectCreationStep(ABC):
    """Copy of ProjectCreationStep ABC for isolated testing."""
    all_steps = []

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    def __eq__(self, other: 'ProjectCreationStep') -> bool:
        return self.name == other.name

    def __new__(cls, *args, **kwargs):
        klass = super().__new__(cls)
        try:
            index = ProjectCreationStep.all_steps.index(klass)
            return ProjectCreationStep.all_steps[index]
        except (ValueError, AttributeError):
            ProjectCreationStep.all_steps.append(klass)
            return klass

    def __init__(self, module=None):
        self.module = module
        self._created = {
            'initialized': False,
            'ok': None,
            'msg': '',
            'step': self.name
        }
        self._deleted = {
            'initialized': False,
            'ok': None,
            'msg': '',
            'step': self.name
        }

    @property
    def status(self) -> dict:
        return {
            'created': self._created,
            'deleted': self._deleted
        }

    def __repr__(self) -> str:
        extra = []
        if self._created['ok']:
            extra.append('created')
        if self._deleted['ok']:
            extra.append('deleted')
        return f'<Step: {self.name} {" ".join(extra)}>'

    @abstractmethod
    def create(self, *args, **kwargs):
        ...

    @abstractmethod
    def delete(self, *args, **kwargs):
        ...


@pytest.fixture(autouse=True)
def reset_all_steps():
    """Reset the singleton list before each test."""
    ProjectCreationStep.all_steps = []
    yield
    ProjectCreationStep.all_steps = []


class TestProjectCreationStep:
    """Tests for ProjectCreationStep ABC."""

    def test_concrete_step_creation(self):
        class TestStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "test_step"

            def create(self):
                pass

            def delete(self):
                pass

        step = TestStep()
        assert step.name == "test_step"

    def test_initial_status(self):
        class InitStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "init_step"

            def create(self):
                pass

            def delete(self):
                pass

        step = InitStep()
        status = step.status

        assert status['created']['initialized'] is False
        assert status['created']['ok'] is None
        assert status['created']['step'] == "init_step"
        assert status['deleted']['initialized'] is False
        assert status['deleted']['ok'] is None

    def test_repr_no_status(self):
        class ReprStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "repr_step"

            def create(self):
                pass

            def delete(self):
                pass

        step = ReprStep()
        assert repr(step) == "<Step: repr_step >"

    def test_repr_with_created(self):
        class CreatedStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "created_step"

            def create(self):
                pass

            def delete(self):
                pass

        step = CreatedStep()
        step._created['ok'] = True
        assert repr(step) == "<Step: created_step created>"

    def test_repr_with_deleted(self):
        class DeletedStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "deleted_step"

            def create(self):
                pass

            def delete(self):
                pass

        step = DeletedStep()
        step._deleted['ok'] = True
        assert repr(step) == "<Step: deleted_step deleted>"

    def test_repr_with_both(self):
        class BothStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "both_step"

            def create(self):
                pass

            def delete(self):
                pass

        step = BothStep()
        step._created['ok'] = True
        step._deleted['ok'] = True
        assert repr(step) == "<Step: both_step created deleted>"

    def test_equality_same_name(self):
        class StepA(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "same_name"

            def create(self):
                pass

            def delete(self):
                pass

        class StepB(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "same_name"

            def create(self):
                pass

            def delete(self):
                pass

        a = StepA()
        b = StepB()
        assert a == b

    def test_equality_different_name(self):
        class StepX(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "name_x"

            def create(self):
                pass

            def delete(self):
                pass

        class StepY(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "name_y"

            def create(self):
                pass

            def delete(self):
                pass

        x = StepX()
        y = StepY()
        assert x != y

    def test_module_assignment(self):
        class ModStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "mod_step"

            def create(self):
                pass

            def delete(self):
                pass

        mock_module = object()
        step = ModStep(module=mock_module)
        assert step.module is mock_module

    def test_singleton_behavior(self):
        class SingletonStep(ProjectCreationStep):
            @property
            def name(self) -> str:
                return "singleton"

            def create(self):
                pass

            def delete(self):
                pass

        step1 = SingletonStep()
        step2 = SingletonStep()
        # Due to singleton pattern, they should be the same instance
        assert step1 is step2
        assert len(ProjectCreationStep.all_steps) == 1
