from odoo import models, fields, _


class SaleOrderApprovalWizard(models.TransientModel):
    _name = 'sale.order.approval.wizard'
    _description = 'Sale Order Approval Wizard'

    # The domain ensures only users in the 'Sales / Manager' group are selectable
    manager_id = fields.Many2one(
        'res.users',
        string="Sales Manager",
        required=True,
        domain=lambda self: [
            ('groups_id', 'in', self.env.ref('rsd_sales.group_sale_approver').id)
        ]
    )

    def action_confirm(self):
        self.ensure_one()
        # Retrieve the active sales order from the context
        active_id = self.env.context.get('active_id')
        if active_id:
            order = self.env['sale.order'].browse(active_id)

            # Update the order and advance the approval state
            order.approval_manager_id = self.manager_id.id
            order.approval_state = 'send_for_approval'

            # Log the action in the chatter
            order.message_post(
                body=_("Sales Order sent for approval to %s") % self.manager_id.name
            )