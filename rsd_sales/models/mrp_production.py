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
    is_packing_order = fields.Boolean(
        string="Is Packing Order",
        default=False,
        help="Check this if this is packing order against the MO."
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Check if the work order flag is set AND the name is not yet set
            if vals.get('is_packing_order') and vals.get('name', 'New') == 'New':
                # Fetch the next sequence number for the Work Order
                vals['name'] = self.env['ir.sequence'].next_by_code('rsd.pi.sequence') or '/'

        return super(MrpProduction, self).create(vals_list)

    @api.onchange('product_id', 'move_raw_ids', 'never_product_template_attribute_value_ids')
    def _onchange_product_id(self):
        """Override to disable the restriction that prevents finished product from being a component."""
        # Do NOT call super — we completely replace the method
        return