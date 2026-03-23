from odoo import models, fields, _, api
import logging

from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_out_of_stock = fields.Boolean(
        string="Out of Stock",
        compute='_compute_is_out_of_stock',
        store=True,
    )

    qty_available = fields.Float(
        string="Quantity Available",
        compute='_compute_qty_available',
        store=True,
        digits='Product Unit of Measure'
    )

    qty_packed_inventory = fields.Float(
        string='Packed Inventory',
        compute='_compute_inventory_quantities',
        store=False,
        readonly=True,
    )
    qty_unpacked_inventory = fields.Float(
        string='Unpacked Inventory',
        compute='_compute_inventory_quantities',
        store=False,
        readonly=True,
    )

    is_production_user_by_dept = fields.Boolean(
        string="Is Production User (by Department)",
        related='order_id.is_production_user_by_dept',
        store=False,
    )

    available_lot_ids = fields.Many2many(
        'stock.lot',
        compute='_compute_available_lots'
    )

    lot_ids = fields.Many2many(
        'stock.lot',
        'sale_line_lot_rel',
        'sale_line_id',
        'lot_id',
        string="Batch No. (Lots)",
        domain="[('id', 'in', available_lot_ids)]"
    )

    @api.depends('product_id', 'order_id.warehouse_id')
    def _compute_available_lots(self):
        for line in self:
            if not line.product_id:
                line.available_lot_ids = [(5, 0, 0)]  # Clear the field safely
                continue

            # Identify the stock location for the current Sales Order's warehouse
            location = line.order_id.warehouse_id.lot_stock_id

            # Use read_group to get the SUM of quantities grouped by lot_id
            # This perfectly handles the positive/negative quant issue in your database
            quant_groups = self.env['stock.quant'].read_group(
                domain=[
                    ('product_id', '=', line.product_id.id),
                    ('location_id', 'child_of', location.id if location else False),
                    ('lot_id', '!=', False)  # Ensure we only look at tracked lots
                ],
                fields=['lot_id', 'quantity', 'reserved_quantity'],
                groupby=['lot_id']
            )

            valid_lot_ids = []
            for group in quant_groups:
                # Calculate Net Quantity: Total Qty - Reserved Qty
                net_qty = group.get('quantity', 0.0) - group.get('reserved_quantity', 0.0)

                if net_qty > 0:
                    # group['lot_id'] is a tuple like (ID, 'Name')
                    valid_lot_ids.append(group['lot_id'][0])

            # Assign the valid lot IDs back to the computed field
            line.available_lot_ids = [(6, 0, valid_lot_ids)]

    @api.depends('product_id')
    def _compute_qty_available(self):
        """
        Computes the quantity available for the product on the sales order line.
        """
        _logger.info("ORDER LINE: _compute_qty_available method triggered.")
        for line in self:
            line.qty_available = line.product_id.virtual_available

    @api.depends('product_id', 'product_uom_qty')
    def _compute_is_out_of_stock(self):
        """
        Computes the is_out_of_stock status for the sales order line.
        """
        _logger.info("ORDER LINE: _compute_is_out_of_stock method triggered.")
        for line in self:
            if not line.product_id or line.product_uom_qty <= 0:
                _logger.info("ORDER LINE: Skipping _compute for empty line.")
                line.is_out_of_stock = False
                continue

            # Use the newly computed qty_available field
            available_qty = line.qty_available
            _logger.info(
                "ORDER LINE: Checking product %s. Requested: %s, Available: %s",
                line.product_id.display_name, line.product_uom_qty, available_qty
            )

            if available_qty < line.product_uom_qty:
                _logger.info(
                    "ORDER LINE: Product %s is out of stock. is_out_of_stock set to True.",
                    line.product_id.display_name
                )
                line.is_out_of_stock = True
            else:
                line.is_out_of_stock = False

    @api.onchange('product_id', 'product_uom_qty')
    def _onchange_product_id_qty_update_parent_state(self):
        """
        This method is triggered by changes to the product or quantity on a sales order line.
        It triggers a re-computation of the parent sales order's `all_in_stock` field,
        which in turn manages the state via the `write` method.
        The direct call to `_update_state_from_stock_availability` has been removed.
        """
        _logger.info("ORDER LINE: Onchange triggered for product or quantity.")
        # Trigger the re-computation of the all_in_stock field on the parent order
        self.order_id._compute_all_in_stock()

    @api.depends('product_id')  # <--- Triggered when product_id changes
    def _compute_inventory_quantities(self):

        packed_loc = self.env['stock.location'].search([('name', '=', 'Packed - FG')], limit=1)
        unpacked_loc = self.env['stock.location'].search([('name', '=', 'Un Packed - FG')], limit=1)

        for line in self:
            if line.product_id:
                if packed_loc:
                    line.qty_packed_inventory = sum(self.env['stock.quant'].search([
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', packed_loc.id)
                    ]).mapped('quantity'))
                else:
                    line.qty_packed_inventory = 0.0

                # Unpacked Quantity
                if unpacked_loc:
                    line.qty_unpacked_inventory = sum(self.env['stock.quant'].search([
                        ('product_id', '=', line.product_id.id),
                        ('location_id', '=', unpacked_loc.id)
                    ]).mapped('quantity'))
                else:
                    line.qty_unpacked_inventory = 0.0
            else:
                line.qty_packed_inventory = 0.0
                line.qty_unpacked_inventory = 0.0

    @api.constrains('product_uom_qty', 'product_packaging_id')
    def _check_packaging_qty_integer(self):
        for line in self:
            product = line.product_id

            if not product.categ_id.is_packaging_category:
                continue

            packaging = line.product_packaging_id
            qty = line.product_uom_qty
            pack_qty = line.product_packaging_qty

            # product_packaging_qty is computed by Odoo
            if pack_qty and not float(pack_qty).is_integer():
                message = _(
                    "Invalid packaging quantity for product '%s'.\n\n"
                    "Ordered quantity: %.2f %s\n"
                    "Packaging: %s (%.2f %s per pack)\n\n"
                    "Computed packaging quantity is %.2f, but packaging "
                    "must always be a whole number.\n\n"
                    "Please adjust the ordered quantity so that the "
                    "packaging quantity becomes an integer."
                ) % (
                              line.product_id.display_name,
                              qty,
                              line.product_uom.name,
                              packaging.display_name,
                              packaging.qty,
                              packaging.product_uom_id.name,
                              pack_qty,
                          )

                raise ValidationError(message)

    @api.depends('state', 'order_id.approval_state')
    def _compute_product_uom_readonly(self):
        for line in self:
            # original Odoo rule
            readonly = line.ids and line.state in ['sale', 'cancel']

            # add your approval workflow rule
            if line.order_id.approval_state != 'draft':
                readonly = True

            line.product_uom_readonly = readonly

    @api.depends('product_id', 'state', 'qty_invoiced', 'qty_delivered', 'order_id.approval_state')
    def _compute_product_updatable(self):
        super()._compute_product_updatable()

        for line in self:
            # If order is not in draft approval state → product should not be editable
            if line.order_id.approval_state != 'draft':
                line.product_updatable = False
