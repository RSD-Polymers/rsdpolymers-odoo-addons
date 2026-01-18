# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _get_packing_picking_type(self):
        return self.env['stock.picking.type'].search([
            ('sequence_code', '=', 'PI'),
            ('code', '=', 'mrp_operation'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

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
        packing_picking_type = self._get_packing_picking_type()

        for vals in vals_list:
            if vals.get('is_packing_order'):
                # 1️⃣ Set Packing Order sequence
                if vals.get('name', 'New') == 'New':
                    vals['name'] = (
                            self.env['ir.sequence']
                            .next_by_code('rsd.pi.sequence') or '/'
                    )

                # 2️⃣ Set Packing Operation Type (CRITICAL)
                if packing_picking_type and not vals.get('picking_type_id'):
                    vals['picking_type_id'] = packing_picking_type.id

        return super().create(vals_list)

    @api.onchange('product_id', 'move_raw_ids', 'never_product_template_attribute_value_ids')
    def _onchange_product_id(self):
        """Override to disable the restriction that prevents finished product from being a component."""
        # Do NOT call super — we completely replace the method
        return

    @api.onchange('is_packing_order')
    def _onchange_is_packing_order(self):
        if self.is_packing_order:
            picking_type = self.env['stock.picking.type'].search([
                ('name', '=', 'Packing Instruction'),
                ('code', '=', 'mrp_operation'),
                ('company_id', '=', self.company_id.id),
            ], limit=1)

            if picking_type:
                self.picking_type_id = picking_type

    @api.constrains('move_raw_ids', 'product_qty')
    def _check_packaging_product_integer_qty(self):
        for mo in self:
            for move in mo.move_raw_ids:
                product = move.product_id

                # Packaging product = packaging defined on product
                if not product.packaging_ids:
                    continue

                qty = move.product_uom_qty

                if qty and not float(qty).is_integer():
                    message = (
                        "Invalid quantity for packaging product '%s'.\n\n"
                        "Computed quantity is %.2f %s.\n\n"
                        "Packaging products must always have a whole number quantity.\n\n"
                        "Please adjust the Manufacturing Order quantity so that "
                        "the packaging quantity becomes an integer."
                    ) % (
                                  product.display_name,
                                  qty,
                                  move.product_uom.name,
                              )

                    raise ValidationError(message)