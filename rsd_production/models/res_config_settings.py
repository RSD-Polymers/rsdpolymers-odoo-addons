# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    allow_production_request_mo_pi = fields.Boolean(
        string="Allow MO/PI Creation from Production Requests",
        config_parameter="rsd_production.allow_production_request_mo_pi",
        help=(
            "When enabled, authorized Production users can create Manufacturing Orders "
            "and Packing Instructions from Production Request lines."
        ),
    )
