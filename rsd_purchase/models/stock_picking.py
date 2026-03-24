from odoo import models, fields, api
from odoo.exceptions import UserError


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    is_grn = fields.Boolean(
        string="Is Receipt Transfer",
        compute='_compute_is_receipt_transfer',
        store=False,
    )

    def _compute_is_receipt_transfer(self):
        for picking in self:
            picking.is_grn = (picking.picking_type_id.code == 'incoming')

    def action_print_grn(self):
        self.ensure_one()
        user = self.env.user
        if user.employee_id and user.employee_id.department_id:
            dept_name = user.employee_id.department_id.name.strip().lower()
            if dept_name in ['purchase', 'purchasing']:
                raise UserError("Purchase department users are not allowed to print the GRN.")
        return self.env.ref('rsd_purchase.action_report_grn').report_action(self, config=False)
