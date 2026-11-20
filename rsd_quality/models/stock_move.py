# -*- coding: utf-8 -*-
from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _create_quality_checks_for_mo(self):
        # Keep Odoo's standard automatic Quality Check generation enabled.
        # The Request Quality button only updates the request status of checks
        # that already exist; it must not generate checks itself.
        return super()._create_quality_checks_for_mo()
