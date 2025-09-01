from odoo import models, fields, _, api
import logging

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
        readonly=True,
    )
    qty_unpacked_inventory = fields.Float(
        string='Unpacked Inventory',
        readonly=True,
    )

    is_production_user_by_dept = fields.Boolean(
        string="Is Production User (by Department)",
        related='order_id.is_production_user_by_dept',
        store=False,
    )

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

    @api.onchange('product_id')
    def _onchange_product_id_inventory(self):
        if self.product_id:
            # Find the stock locations for packed and unpacked inventory
            packed_loc = self.env['stock.location'].search([('name', '=', 'FG/Packed')], limit=1)
            unpacked_loc = self.env['stock.location'].search([('name', '=', 'FG/Unpacked')], limit=1)

            # Get the quantities from these locations
            if packed_loc:
                self.qty_packed_inventory = sum(self.env['stock.quant'].search(
                    [('product_id', '=', self.product_id.id), ('location_id', '=', packed_loc.id)]
                ).mapped('quantity'))
            else:
                self.qty_packed_inventory = 0.0

            if unpacked_loc:
                self.qty_unpacked_inventory = sum(self.env['stock.quant'].search(
                    [('product_id', '=', self.product_id.id), ('location_id', '=', unpacked_loc.id)]
                ).mapped('quantity'))
            else:
                self.qty_unpacked_inventory = 0.0
        else:
            self.qty_packed_inventory = 0.0
            self.qty_unpacked_inventory = 0.0