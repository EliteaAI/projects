""" Project operations for SCIM provisioning (#5202). Called only by the admin plugin's SCIM sync. """
from pylon.core.tools import web, log  # pylint: disable=E0611,E0401
from sqlalchemy import func  # pylint: disable=E0401
from tools import rpc_tools, db  # pylint: disable=E0401

from ..models.pd.project import ProjectCreatePD
from ..models.project import Project
from ..utils.project_steps import create_project


class RPC:  # pylint: disable=R0903
    @web.rpc("projects_scim_create")
    @rpc_tools.wrap_exceptions(RuntimeError)
    def projects_scim_create(self, name: str, owner_id: int) -> int:
        """ A team project without a human admin; its members are added by the SCIM sync """
        context = {
            "project_model": ProjectCreatePD(name=name, project_admin_email=None, plugins=[]),
            "owner_id": owner_id,
            "roles": ["viewer"],
        }
        create_project(self, context)
        project_id = context["project"].id
        log.info("SCIM: created project %s (%s)", project_id, name)
        return project_id

    @web.rpc("projects_scim_set_suspended")
    @rpc_tools.wrap_exceptions(RuntimeError)
    def projects_scim_set_suspended(self, project_id: int, suspended: bool) -> None:
        with db.get_session(None) as session:
            project = session.query(Project).where(Project.id == project_id).first()
            if project is None:
                raise RuntimeError(f"Project {project_id} not found")
            project.suspended = bool(suspended)
            session.commit()
        try:
            user_ids = self.context.rpc_manager.call.admin_get_users_ids_in_project(project_id)
            self.context.rpc_manager.call.clear_user_projects_cache(user_ids)
        except Exception:  # pylint: disable=W0703
            log.warning("SCIM: project %s caches were not cleared", project_id)

    @web.rpc("projects_scim_name")
    @rpc_tools.wrap_exceptions(RuntimeError)
    def projects_scim_name(self, project_id: int):
        """ The project's current name, None when it no longer exists """
        with db.get_session(None) as session:
            return session.query(Project.name).where(Project.id == project_id).scalar()

    @web.rpc("projects_scim_find_by_name")
    @rpc_tools.wrap_exceptions(RuntimeError)
    def projects_scim_find_by_name(self, name: str) -> list:
        """ Ids of the active team projects named ``name`` (case-insensitive); a group is linked to one of them """
        with db.get_session(None) as session:
            return [pid for (pid,) in session.query(Project.id).where(
                func.lower(Project.name) == name.strip().lower(),
                ~Project.name.like("project_user_%"),
                Project.suspended.is_(False),
            ).order_by(Project.id)]
