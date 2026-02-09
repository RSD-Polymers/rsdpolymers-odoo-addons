import logging
from odoo import api, Command, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import format_date
import calendar

_logger = logging.getLogger(__name__)


class HrPayrollPayslip(models.Model):
    _inherit='hr.payslip'

    number_of_days = fields.Float('Number of days', compute="_compute_number_of_days")
    leaves = fields.Float('Leaves', compute="_compute_leaves_taken")
    weakoff = fields.Float('Weak Offs')


    @api.depends('date_from','date_to')
    def _compute_number_of_days(self):
        for rec in self:
            if rec.date_from and rec.date_to:
                rec.number_of_days = (rec.date_to - rec.date_from).days
            else:
                rec.number_of_days = 0.0

    @api.depends('line_ids')
    def _compute_leaves_taken(self):
        for rec in self:
            leave = self.env['hr.leave'].sudo().search([('request_date_from','<=',rec.date_from),('request_date_to','>=',rec.date_from),('employee_id','=',rec.employee_id.id)])
            rec.leaves = sum(leave.mapped('number_of_days')) if sum(leave.mapped('number_of_days')) else 0.0
            cal = calendar.Calendar()
            sundays = [day for day in cal.itermonthdates(rec.date_from.year, rec.date_from.month) if day.weekday() == 6 and day.month == rec.date_from.month]
            rec.weakoff = len(sundays)

    def action_print_payslip(self):
        return self.env.ref(
            'portal_attendance_leave.action_custom_payslip_report'
        ).report_action(self, config=False)

    @api.model_create_multi
    def create(self, vals_list):
        slips = super().create(vals_list)

        for slip in slips:
            if not slip.employee_id:
                continue

            contract = slip.contract_id or slip.employee_id.contract_id
            if not contract:
                continue

            structure = self.env["hr.payroll.structure"].search([
                ("employee_id", "=", slip.employee_id.id),
                ("type_id", "=", contract.structure_type_id.id),
            ], limit=1)

            if structure:
                slip.struct_id = structure.id

        return slips


