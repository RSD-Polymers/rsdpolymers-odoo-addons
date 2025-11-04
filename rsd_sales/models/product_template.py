from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    hide_default_code = fields.Boolean(compute='_compute_hide_default_code', store=False)

    @api.depends()  # Add appropriate depends if needed
    def _compute_hide_default_code(self):
        for record in self:
            user = self.env.user
            # Skip check for admin (user with ID=1) or superuser
            if user.id == 1 or user.has_group('base.group_system'):
                record.hide_default_code = False
                continue

            try:
                # Use sudo() to avoid access errors for hr.employee and department
                employee = self.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
                if employee and employee.department_id.name == 'Store':
                    record.hide_default_code = True
                else:
                    record.hide_default_code = False
            except Exception:
                # In case of any error (e.g. no access), default to False
                record.hide_default_code = False
