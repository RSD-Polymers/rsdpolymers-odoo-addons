from odoo import models, fields

class HrLeaveType(models.Model):
    _inherit = "hr.leave.type"

    is_out_duty = fields.Boolean(
        string="Is Out Duty",
        help="Tick if this leave type is Out Duty."
    )
