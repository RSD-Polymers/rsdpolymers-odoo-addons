from odoo import models, fields, api
from odoo.exceptions import UserError


class QualityCheck(models.Model):
    _inherit = 'quality.check'

    is_quality_dept_user = fields.Boolean(
        compute='_compute_is_quality_dept_user'
    )

    def _compute_is_quality_dept_user(self):
        user = self.env.user

        # Determine if the user is in the Quality department (or is an Admin)
        is_quality = False
        if user.has_group('base.group_system'):
            is_quality = True
        elif user.employee_id and user.employee_id.department_id:
            dept_name = user.employee_id.department_id.name.strip().lower()
            if 'qc' in dept_name:
                is_quality = True

        for check in self:
            check.is_quality_dept_user = is_quality

    def _ensure_quality_department(self):
        """Helper to block the action if the user is not in Quality."""
        for check in self:
            if not check.is_quality_dept_user:
                raise UserError(
                    "Access Denied: Only users from the Quality Department are allowed to perform Quality Checks.")

    def do_pass(self):
        # 1. Block unauthorized users
        self._ensure_quality_department()
        # 2. Proceed with standard Odoo logic
        return super(QualityCheck, self).do_pass()

    def do_fail(self):
        # 1. Block unauthorized users
        self._ensure_quality_department()
        # 2. Proceed with standard Odoo logic
        return super(QualityCheck, self).do_fail()