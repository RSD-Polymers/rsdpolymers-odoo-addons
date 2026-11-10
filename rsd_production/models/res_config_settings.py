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

    enable_rm_consumption_variance_tracking = fields.Boolean(
        string="Enable Raw Material Consumption Variance Tracking",
        config_parameter="rsd_production.enable_rm_consumption_variance_tracking",
        default=False,
        help=(
            "When enabled, the Output Form will compare planned BoM consumption with "
            "actual raw material consumption and display any additional consumption."
        ),
    )
    require_rm_consumption_variance_reason = fields.Boolean(
        string="Require Reason for Additional Consumption",
        config_parameter="rsd_production.require_rm_consumption_variance_reason",
        default=True,
        help="Require the Production Coordinator to explain additional raw material consumption.",
    )
    allow_rm_consumption_variance_reason_breakdown = fields.Boolean(
        string="Allow Quantity-wise Reason Breakdown",
        config_parameter="rsd_production.allow_rm_consumption_variance_reason_breakdown",
        default=True,
        help=(
            "Allow the additional consumption to be split into multiple reason lines, "
            "each with its own quantity and explanation."
        ),
    )
