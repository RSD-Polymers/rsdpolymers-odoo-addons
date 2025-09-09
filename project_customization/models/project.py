from odoo import models, api
from odoo.osv import expression

class ProjectProject(models.Model):
    _inherit = 'project.project'

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
        """
        Overrides the _search method to implement custom security logic,
        with added robustness for internal Odoo calls.
        """
        if self.env.user.has_group('base.group_system'):
            try:
                # Try the full super call
                return super(ProjectProject, self)._search(
                    args, offset=offset, limit=limit, order=order, count=count, access_rights_uid=access_rights_uid
                )
            except TypeError:
                # Fallback to the simplest super call
                return super(ProjectProject, self)._search(args, offset=offset, limit=limit, order=order)

        security_domain = []

        if self.env.user.login == 'nilesh@rsdpolymers.com':
            department_ids = self.env['hr.department'].search([
                ('name', 'in', ['QC', 'QA', 'Stores', 'Production'])
            ]).ids
            security_domain = ['|', ('user_id', '=', self.env.user.id), ('user_id.employee_id.department_id', 'in', department_ids)]
        else:
            security_domain = [('user_id', '=', self.env.user.id)]

        combined_domain = expression.AND([args, security_domain])

        try:
            # Try the full super call
            return super(ProjectProject, self)._search(
                combined_domain, offset=offset, limit=limit, order=order, count=count, access_rights_uid=access_rights_uid
            )
        except TypeError:
            # Fallback to the simplest super call
            return super(ProjectProject, self)._search(combined_domain, offset=offset, limit=limit, order=order)