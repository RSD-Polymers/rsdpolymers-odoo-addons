from odoo import fields, models, _
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
    rsd_accounts_involved = fields.Boolean(
        string='Accounts Involved',
        copy=False,
        readonly=True,
        tracking=True,
    )
    rsd_finance_involved = fields.Boolean(
        string='Finance Involved',
        copy=False,
        readonly=True,
        tracking=True,
    )

    def _notify_rsd_group(self, group_xmlid, subject, body):
        group = self.env.ref(group_xmlid)
        partner_ids = group.users.mapped('partner_id').ids
        if partner_ids:
            self.message_notify(
                partner_ids=partner_ids,
                subject=subject,
                body=body,
            )

    def _do_approve(self):
        result = super()._do_approve()
        for sheet in self:
            if not sheet.rsd_payment_id:
                sheet.write({
                    'rsd_payment_state': 'accounts_review',
                    'rsd_send_back_reason': False,
                    'rsd_accounts_involved': True,
                    'rsd_finance_involved': False,
                })
                sheet._notify_rsd_group(
                    'rsd_payment.group_rsd_payment_accounts',
                    _('Expense Report Ready for Accounts Review'),
                    _(
                        'Expense Report <b>%s</b> is ready for Accounts Review.'
                    ) % sheet.display_name,
                )
        return result

    def write(self, vals):
        if not self.env.context.get('rsd_payment_internal_write'):
            if self.env.user.has_group('base.group_system'):
                return super().write(vals)

            accounts_user = self.env.user.has_group(
                'rsd_payment.group_rsd_payment_accounts'
            )
            finance_user = self.env.user.has_group(
                'rsd_payment.group_rsd_payment_finance'
            )

            if accounts_user and finance_user:
                # A user belonging to both workflow groups can edit in either
                # active review stage, but not after Finance approval.
                if any(sheet.rsd_payment_state not in ('accounts_review', 'finance_review') for sheet in self):
                    raise UserError(_(
                        'Expense Reports can only be edited during Accounts Review or Finance Review.'
                    ))
            elif accounts_user:
                if any(sheet.rsd_payment_state != 'accounts_review' for sheet in self):
                    raise UserError(_(
                        'Expense Reports can only be edited by Accounts while they are in Accounts Review.'
                    ))
            elif finance_user:
                if any(sheet.rsd_payment_state != 'finance_review' for sheet in self):
                    raise UserError(_(
                        'Expense Reports can only be edited by Finance while they are in Finance Review.'
                    ))

        return super().write(vals)

    def action_rsd_send_to_finance(self):
        self.ensure_one()
        if not self.env.user.has_group('rsd_payment.group_rsd_payment_accounts'):
            raise UserError(_('Only Accounts users can send Expense Reports to Finance.'))
        if self.rsd_payment_state != 'accounts_review':
            raise UserError(_('Only Expense Reports in Accounts Review can be sent to Finance.'))
        if self.rsd_payment_id:
            raise UserError(_('An RSD Payment already exists for this Expense Report.'))

        self.with_context(rsd_payment_internal_write=True).write({
            'rsd_payment_state': 'finance_review',
            'rsd_send_back_reason': False,
            'rsd_accounts_involved': True,
            'rsd_finance_involved': True,
        })
        self._notify_rsd_group(
            'rsd_payment.group_rsd_payment_finance',
            _('Expense Report Ready for Finance Review'),
            _(
                'Expense Report <b>%s</b> has been sent to Finance for review.'
            ) % self.display_name,
        )
        return True

    def action_rsd_send_back_to_accounts(self, reason=False):
        self.ensure_one()
        if not self.env.user.has_group('rsd_payment.group_rsd_payment_finance'):
            raise UserError(_('Only Finance users can send Expense Reports back to Accounts.'))
        if self.rsd_payment_state != 'finance_review':
            raise UserError(_('Only Expense Reports in Finance Review can be sent back.'))
        if self.rsd_payment_id:
            raise UserError(_('An RSD Payment already exists for this Expense Report.'))
        if not reason or not reason.strip():
            raise UserError(_('A reason is required when sending an Expense Report back.'))

        self.with_context(rsd_payment_internal_write=True).write({
            'rsd_payment_state': 'accounts_review',
            'rsd_send_back_reason': reason,
            'rsd_accounts_involved': True,
            'rsd_finance_involved': True,
        })
        self._notify_rsd_group(
            'rsd_payment.group_rsd_payment_accounts',
            _('Expense Report Sent Back by Finance'),
            _(
                'Expense Report <b>%s</b> has been sent back by Finance for review.<br/><br/>'
                '<b>Reason:</b> %s'
            ) % (self.display_name, reason),
        )
        return True
