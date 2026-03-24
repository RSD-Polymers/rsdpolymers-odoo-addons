from odoo import models, fields, api
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_purchase_dept_user = fields.Boolean(
        compute='_compute_is_purchase_dept_user'
    )

    def _compute_is_purchase_dept_user(self):
        user = self.env.user
        is_purchase = False

        # Check if the user is linked to an employee in the Purchase department
        if user.employee_id and user.employee_id.department_id:
            is_purchase = user.employee_id.department_id.name.strip().lower() in ['purchase', 'purchasing']

        for picking in self:
            picking.is_purchase_dept_user = is_purchase

    def button_validate(self):
        """
        Backend security override: Prevent Purchase users from bypassing
        the hidden UI buttons and validating via RPC or Server Actions.
        """
        for picking in self:
            if picking.is_purchase_dept_user:
                raise UserError(
                    "Purchase department users are not allowed to validate warehouse receipts or deliveries.")

        return super(StockPicking, self).button_validate()