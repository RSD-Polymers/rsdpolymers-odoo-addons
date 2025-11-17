from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'
    

    # Partner-level mapping to use Tally-imported accounts
    tally_receivable_account_id = fields.Many2one(
    'account.account',
    string='Tally Receivable Account',
    help='Account (from imported Tally ledgers) to use for receivables for this partner.'
    )


    tally_payable_account_id = fields.Many2one(
    'account.account',
    string='Tally Payable Account',
    help='Account (from imported Tally ledgers) to use for payables for this partner.'
    )


    tally_sales_account_id = fields.Many2one(
    'account.account',
    string='Tally Sales Account',
    help='Default sales ledger (Tally) to use on customer invoice lines for this partner.'
    )


    tally_purchase_account_id = fields.Many2one(
    'account.account',
    string='Tally Purchase Account',
    help='Default purchase ledger (Tally) to use on vendor bill lines for this partner.'
    )