from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'
    

    tally_sales_ledger_id = fields.Many2one(
    'account.account',
    string='Tally Sales Ledger',
    help='If set, this account will be used for product sales lines (customer invoices) unless partner mapping overrides it.'
    )


    tally_purchase_ledger_id = fields.Many2one(
    'account.account',
    string='Tally Purchase Ledger',
    help='If set, this account will be used for product purchase lines (vendor bills) unless partner mapping overrides it.'
    )