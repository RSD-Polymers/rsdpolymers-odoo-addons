from odoo import models, fields, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class SaleCreateMoWizard(models.TransientModel):
    _name = 'sale.create.mo.wizard'
    _description = 'Create Manufacturing Order Wizard'

    is_packing_order = fields.Boolean(
        string="Packing Instruction",
        help="If checked, Manufacturing Orders will be created as Packing Instructions."
    )

    def action_confirm_create_mo(self):
        """Call SO method with packing flag"""
        sale_order = self.env['sale.order'].browse(self.env.context.get('active_id'))
        if not sale_order:
            raise UserError(_("No Sales Order found."))

        _logger.info(
            "MO WIZARD: Creating MO for SO %s | Packing=%s",
            sale_order.name,
            self.is_packing_order
        )

        sale_order._action_create_mrp_orders_from_wizard(
            is_packing_order=self.is_packing_order
        )

        return {'type': 'ir.actions.act_window_close'}
