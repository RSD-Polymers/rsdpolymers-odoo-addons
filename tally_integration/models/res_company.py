from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    msme_no = fields.Char(
        string="MSME No",
        help="Enter MSME Registration Number"
    )