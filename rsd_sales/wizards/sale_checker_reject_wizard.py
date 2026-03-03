from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SaleCheckerRejectWizard(models.TransientModel):
    _name = 'sale.order.checker.reject.wizard'
    _description = 'Checker Reject Wizard'

    remark = fields.Text(string="Rejection Reason", required=True)

    def action_confirm_rejection(self):
        self.ensure_one()

        sale = self.env['sale.order'].browse(self.env.context.get('active_id'))

        if not sale:
            raise UserError(_("Sale Order not found"))

        if sale.approval_state != 'send_for_checking':
            raise UserError(_("Order is not waiting for checking"))

        # Timestamp
        timestamp = fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # Build remark block
        new_remark = (
            f"Rejected on {timestamp} by {self.env.user.name} (Checker):\n"
            f"{self.remark}\n"
            f"--------------------------------------------------\n"
        )

        # Append previous remarks
        existing_remarks = sale.rejection_remarks or ""

        sale.write({
            'approval_state': 'draft',
            'rejection_remarks': new_remark + existing_remarks,
        })

        sale.message_post(body=_(
            "Order rejected by Checker.<br/><b>Reason:</b><br/>%s"
        ) % self.remark)

        return {'type': 'ir.actions.act_window_close'}