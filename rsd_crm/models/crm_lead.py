# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

class CrmLead(models.Model):
    _inherit = "crm.lead"

    product_qty = fields.Float(
        string="Product Qty",
        store=True,
        help="Total quantity of all products from quotations/orders linked to this opportunity.",
    )
    product_avg_price = fields.Float(
        string="Product Average Price",
        store=True,
        help="Quantity-weighted average price across all linked quotation/order lines.",
    )
    expected_revenue = fields.Monetary(
        string='Expected Revenue',
        currency_field='company_currency',
        # The new compute method is named differently to avoid conflict,
        # but because we are redefining the field, Odoo will use this one.
        compute='_compute_custom_expected_revenue',
        store=True,
        tracking=True,
        aggregator='avg',
    )

    product_id = fields.Many2one('product.product', string='Product', required=True, index=True)

    payment_term_id = fields.Many2one('account.payment.term', string='Payment Terms')

    @api.depends('product_qty', 'product_avg_price')
    def _compute_custom_expected_revenue(self):
        """
        Calculates the expected revenue based on the quantity and average price of the product.
        This method correctly overrides the core Odoo calculation without removing any code.
        """
        for lead in self:
            lead.expected_revenue = lead.product_qty * lead.product_avg_price

    @api.constrains('product_id', 'date_deadline')
    def _check_unique_product_per_month(self):
        for record in self:
            if record.product_id and record.date_deadline:
                # Extract the month and year from the deadline date
                record_month = record.date_deadline.month
                record_year = record.date_deadline.year

                # Search for existing leads with the same product in the same month and year
                leads_count = self.search_count([
                    ('id', '!=', record.id),  # Exclude the current record
                    ('product_id', '=', record.product_id.id),
                    ('date_deadline', '>=', record.date_deadline.replace(day=1)),
                    ('date_deadline', '<=',
                     record.date_deadline.replace(day=1, month=record_month, year=record_year) + relativedelta(months=1,
                                                                                                               days=-1))
                ])

                if leads_count > 0:
                    raise ValidationError(
                        "There is already a record in the CRM for this product in the selected month."
                    )
