# -*- coding: utf-8 -*-

from odoo import api, fields, models


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

    @api.depends('product_qty', 'product_avg_price')
    def _compute_custom_expected_revenue(self):
        """
        Calculates the expected revenue based on the quantity and average price of the product.
        This method correctly overrides the core Odoo calculation without removing any code.
        """
        for lead in self:
            lead.expected_revenue = lead.product_qty * lead.product_avg_price


