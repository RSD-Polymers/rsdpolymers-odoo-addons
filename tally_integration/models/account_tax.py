from odoo import models, fields


class AccountTax(models.Model):
    _inherit = 'account.tax'


    tally_tax_account_id = fields.Many2one(
    'account.account',
    string='Tally Tax Account',
    help='Map this tax to a specific Tally ledger account. Will be used when creating tax journal items.'
    )