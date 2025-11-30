from odoo import models, fields, api


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    # Add fields to store Rate and Amount on the GRN line
    po_rate = fields.Float(
        'Rate',
        compute='_compute_po_price',
        store=True,
        digits='Product Price'
    )
    po_amount = fields.Float(
        'Amount',
        compute='_compute_po_price',
        store=True,
        digits='Product Price'
    )

    # Compute method to link to the Purchase Order Line
    @api.depends('picking_id.purchase_id')
    def _compute_po_price(self):
        """Fetches the price from the source Purchase Order line."""
        for line in self:
            po_line = self.env['purchase.order.line'].search([
                ('order_id', '=', line.picking_id.purchase_id.id),
                ('product_id', '=', line.product_id.id),
                # Add more constraints (e.g., matching quantities) if needed for uniqueness
            ], limit=1)

            if po_line:
                rate = po_line.price_unit
                line.po_rate = rate
                line.po_amount = line.qty_done * rate
            else:
                line.po_rate = 0.0
                line.po_amount = 0.0