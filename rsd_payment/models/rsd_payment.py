from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RsdPayment(models.Model):
    _name = 'rsd.payment'
    _description = 'Payment Desk'
    _order = 'id desc'

    name = fields.Char(
        string='Payment No.',
        required=True,
        readonly=True,
        copy=False,
        default='New',
    )
    expense_sheet_id = fields.Many2one(
        'hr.expense.sheet',
        string='Expense Report',
        required=True,
        readonly=True,
        copy=False,
        ondelete='restrict',
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        related='expense_sheet_id.employee_id',
        store=True,
        readonly=True,
    )
    amount = fields.Monetary(
        string='Amount',
        related='expense_sheet_id.total_amount',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='expense_sheet_id.currency_id',
        store=True,
        readonly=True,
    )
    approval_date = fields.Date(
        string='Finance Approval Date',
        readonly=True,
        copy=False,
    )
    payment_date = fields.Date(
        string='Payment Date',
        required=True,
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ('unpaid', 'Unpaid'),
            ('paid', 'Paid'),
        ],
        string='Payment Status',
        default='unpaid',
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )
    created_by = fields.Many2one(
        'res.users',
        string='Created By',
        readonly=True,
        copy=False,
        default=lambda self: self.env.user,
    )

    _sql_constraints = [
        (
            'unique_expense_sheet',
            'unique(expense_sheet_id)',
            'An RSD Payment already exists for this Expense Report.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('rsd.payment') or 'New'
                )
            vals.setdefault('state', 'unpaid')
        return super().create(vals_list)

    def action_mark_paid(self):
        if not self.env.user.has_group('rsd_payment.group_rsd_payment_hod'):
            raise UserError(_('Only HOD users can mark a Payment Desk request as Paid.'))
        for payment in self:
            if payment.state == 'paid':
                continue
            payment.write({'state': 'paid'})
        return True
