# -*- coding: utf-8 -*-
from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _create_quality_checks_for_mo(self):
        # Enterprise calls this from stock-move confirmation and MO backorder
        # confirmation. Suppress those automatic calls; the explicit MO button
        # re-enters the unchanged Enterprise implementation with this context.
        if not self.env.context.get("rsd_quality_manual_request"):
            return True
        return super()._create_quality_checks_for_mo()
