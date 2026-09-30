from odoo import fields, models
from odoo.exceptions import UserError


class RsdFinanceSendBackWizard(models.TransientModel):
    _name = 'rsd.finance.send.back.wizard'
    _description = 'RSD Finance Send Back'

    reason = fields.Text(
        string='Reason',
        required=True,
    )

    def action_send_back(self):
        self.ensure_one()

        if not self.env.user.has_group('rsd_payment.group_rsd_payment_finance'):
            raise UserError('Only Finance users can send Expense Reports back.')

        sheet = self.env['hr.expense.sheet'].browse(
            self.env.context.get('active_id')
        ).exists()

        if not sheet:
            raise UserError('Expense Report not found.')

        sheet.ensure_one()
        sheet.action_rsd_send_back_to_accounts(self.reason)

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'hr.expense.sheet',
            'view_mode': 'form',
            'res_id': sheet.id,
            'target': 'current',
        }
