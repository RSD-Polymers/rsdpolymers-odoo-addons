# -*- coding: utf-8 -*-

from odoo import models, fields, api

class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    # Add a Many2one field to link a Manufacturing Order back to its Sales Order
    origin_sale_id = fields.Many2one('sale.order', string='Sales Order', help='The sales order that originated this manufacturing order.')
    production_request_type = fields.Selection(
        selection=[
            ('min_inventory', 'Minimum Inventory Level'),
            ('trial', 'Trial for Process Development'),
            ('order', 'Customer Order'),
        ],
        string="Type Of Production Request",
        help="Type of production request from the sales department."
    )