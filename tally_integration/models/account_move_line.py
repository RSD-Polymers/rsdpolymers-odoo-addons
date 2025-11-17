from odoo import models, api, _
from odoo.exceptions import ValidationError

class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    @api.onchange('product_id')
    def _onchange_product_id_tally_account(self):
        """
        When a product is selected on a move line, set `account_id` using the following priority:
          1. Partner-level mapping (move.partner_id.tally_purchase_account_id / tally_sales_account_id)
          2. Product-level mapping (product.tally_purchase_ledger_id / tally_sales_ledger_id)
          3. Default Odoo behavior (leave as-is)
        """
        for line in self:
            move = line.move_id
            # only act on invoice/bill product lines
            if move.move_type not in ('in_invoice', 'out_invoice'):
                continue

            partner = move.partner_id

            # Vendor Bill
            if move.move_type == 'in_invoice':
                # 1. Partner-level purchase ledger
                if partner and partner.tally_purchase_account_id:
                    line.account_id = partner.tally_purchase_account_id
                    continue

                # 2. Product-level purchase ledger
                if line.product_id and line.product_id.tally_purchase_ledger_id:
                    line.account_id = line.product_id.tally_purchase_ledger_id
                    continue

            # Customer Invoice
            if move.move_type == 'out_invoice':
                # 1. Partner-level sales ledger
                if partner and partner.tally_sales_account_id:
                    line.account_id = partner.tally_sales_account_id
                    continue

                # 2. Product-level sales ledger
                if line.product_id and line.product_id.tally_sales_ledger_id:
                    line.account_id = line.product_id.tally_sales_ledger_id
                    continue

    @api.model
    def create(self, vals):
        # Ensure that partner-level receivable/payable mapping is used for header accounts
        move_vals = {}
        if vals.get('move_id'):
            move = self.env['account.move'].browse(vals['move_id'])
            # for moved lines representing receivable/payable (not product lines) we do not override here
        return super().create(vals)