from odoo import models, api
from odoo.exceptions import AccessError


class ProjectProject(models.Model):
    _inherit = 'project.project'

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False):
        user = self.env.user
        original_domain = list(args) if args is not None else []

        try:
            self.browse().check_access('read')
        except AccessError:
            return self.browse([])

        # 🛡️ Admin users: no filtering
        if user.has_group('base.group_system'):
            args = original_domain

        # 👤 Nilesh Bagwe: filter by specific departments
        elif user.login == 'nilesh.bagwe':
            department_refs = [
                'hr.dep_qc',
                'hr.dep_qa',
                'hr.dep_store',
                'hr.dep_production'
            ]
            department_ids = [
                self.env.ref(dep_ref).id
                for dep_ref in department_refs
                if self.env.ref(dep_ref, raise_if_not_found=False)
            ]
            args += [('department_id', 'in', department_ids)]

        # 3️⃣ L3 group users: filter by manager assignment
        elif self.env.ref('project.group_user_l3') in user.groups_id:
            args += [('user_id', '=', user.id)]

        return super()._search(args, offset=offset, limit=limit, order=order)
