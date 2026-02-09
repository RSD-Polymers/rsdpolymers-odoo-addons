from odoo import models, fields

class HrPayrollStructure(models.Model):
    _inherit = "hr.payroll.structure"

    employee_id = fields.Many2one(
        "hr.employee",
        string="Employee",
        help="Employee-specific salary structure"
    )
