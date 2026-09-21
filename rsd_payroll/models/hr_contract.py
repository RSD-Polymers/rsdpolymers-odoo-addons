from odoo import fields, models


class HrContract(models.Model):
    _inherit = "hr.contract"

    monthly_ctc = fields.Monetary(
        string="Monthly CTC",
        currency_field="currency_id",
        help="Monthly Cost to Company for this employee.",
    )