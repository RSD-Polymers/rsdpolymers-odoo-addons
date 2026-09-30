from odoo import fields, models
from odoo.exceptions import UserError


class HrExpenseSheet(models.Model):
    _inherit = 'hr.expense.sheet'

    rsd_payment_state = fields.Selection(
        [
            ('accounts_review', 'Accounts Review'),
            ('finance_review', 'Finance Review'),
            ('finance_approved', 'Finance Approved'),
        ],
        string='RSD Payment Stage',
        copy=False,
        tracking=True,
    )
    rsd_payment_id = fields.Many2one(
        'rsd.payment',
        string='RSD Payment',
        readonly=True,
        copy=False,
        index=True,
    )
    rsd_send_back_reason = fields.Text(
        string='Finance Send Back Reason',
        readonly=True,
        copy=False,
        tracking=True,
    )

    def _do_approve(self):
        result = super()._do_approve()
        for sheet in self:
            if not sheet.rsd_payment_id:
                sheet.rsd_payment_state = 'accounts_review'
                sheet.rsd_send_back_reason = False
        return result

    def action_rsd_send_to_finance(self):
        self.ensure_one()
        if not self.env.user.has_group('rsd_payment.group_rsd_payment_accounts'):
            raise UserError('Only Accounts users can send Expense Reports to Finance.')
        if self.rsd_payment_state != 'accounts_review':
            raise UserError('Only Expense Reports in Accounts Review can be sent to Finance.')
        if self.rsd_payment_id:
            raise UserError('An RSD Payment already exists for this Expense Report.')

        self.write({
            'rsd_payment_state': 'finance_review',
            'rsd_send_back_reason': False,
        })
        return True

    def action_rsd_send_back_to_accounts(self, reason=False):
        self.ensure_one()
        if not self.env.user.has_group('rsd_payment.group_rsd_payment_finance'):
            raise UserError('Only Finance users can send Expense Reports back to Accounts.')
        if self.rsd_payment_state != 'finance_review':
            raise UserError('Only Expense Reports in Finance Review can be sent back.')
        if self.rsd_payment_id:
            raise UserError('An RSD Payment already exists for this Expense Report.')

        self.write({
            'rsd_payment_state': 'accounts_review',
            'rsd_send_back_reason': reason or False,
        })
        return True
