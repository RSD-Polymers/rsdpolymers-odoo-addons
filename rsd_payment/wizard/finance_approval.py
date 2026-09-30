from odoo import fields, models
from odoo.exceptions import UserError


class RsdFinanceApprovalWizard(models.TransientModel):
    _name = 'rsd.finance.approval.wizard'
    _description = 'RSD Finance Approval'

    payment_date = fields.Date(
        string='Payment Date',
        required=True,
        default=fields.Date.context_today,
    )

    def action_approve(self):
        self.ensure_one()

        if not self.env.user.has_group('rsd_payment.group_rsd_payment_finance'):
            raise UserError('Only Finance users can approve an RSD Payment.')

        sheet = self.env['hr.expense.sheet'].browse(
            self.env.context.get('active_id')
        ).exists()

        if not sheet:
            raise UserError('Expense Report not found.')

        sheet.ensure_one()

        if sheet.rsd_payment_state != 'finance_review':
            raise UserError(
                'Only Expense Reports in Finance Review can be approved.'
            )

        if sheet.rsd_payment_id:
            raise UserError(
                'An RSD Payment already exists for this Expense Report.'
            )

        payment = self.env['rsd.payment'].create({
            'expense_sheet_id': sheet.id,
            'approval_date': fields.Date.context_today(sheet),
            'payment_date': self.payment_date,
        })

        sheet.write({
            'rsd_payment_state': 'finance_approved',
            'rsd_payment_id': payment.id,
            'rsd_send_back_reason': False,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': 'RSD Payment',
            'res_model': 'rsd.payment',
            'view_mode': 'form',
            'res_id': payment.id,
            'target': 'current',
        }
