from odoo import models, fields, _
from datetime import datetime
from odoo.exceptions import UserError
from markupsafe import Markup


class SaleOrderRejectWizard(models.TransientModel):
    _name = 'sale.order.reject.wizard'
    _description = 'Sale Order Rejection Wizard'

    reject_reason = fields.Text(string="Rejection Remark", required=True)

    def action_reject_confirm(self):
        self.ensure_one()
        active_id = self.env.context.get('active_id')
        if not active_id:
            raise UserError(_("Context lost: Could not find the Sale Order."))

        order = self.env['sale.order'].browse(active_id)

        # Format the new remark with a timestamp and user name
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_remark = (
            f"Rejected on {timestamp} by {self.env.user.name}:\n"
            f"{self.reject_reason}\n"
            f"--------------------------------------------------\n"
        )

        # Append to existing remarks
        existing_remarks = order.rejection_remarks or ""

        order.write({
            'approval_state': 'rejected',
            'rejection_remarks': new_remark + existing_remarks,
        })

        order.message_post(body=_("Order rejected. Remark history updated."))
        return {'type': 'ir.actions.act_window_close'}