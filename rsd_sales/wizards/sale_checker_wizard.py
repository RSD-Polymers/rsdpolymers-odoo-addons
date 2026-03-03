from odoo import models, fields, _
from odoo.exceptions import UserError


class SaleOrderCheckerWizard(models.TransientModel):
    _name = 'sale.order.checker.wizard'
    _description = 'Select Sales Executive-BD (Checker)'

    checker_id = fields.Many2one(
        'res.users',
        string="Sales Executive-BD (Checker)",
        required=True
    )

    def action_confirm_checker(self):

        sale_order = self.env['sale.order'].browse(self.env.context.get('active_id'))

        if not sale_order:
            raise UserError(_("No sales order found"))

        sale_order.write({
            'checker_id': self.checker_id.id,
            'approval_state': 'send_for_checking'
        })

        sale_order.message_post(
            body=_("Order sent for checking to %s") % self.checker_id.name
        )