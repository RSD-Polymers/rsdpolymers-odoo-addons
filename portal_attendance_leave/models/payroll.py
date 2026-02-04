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

class HrPayslipEmployees(models.TransientModel):
    _inherit = 'hr.payslip.employees'

    def compute_sheet(self):
        # 1. Get the active Batch (Payslip Run)
        payslip_run = self.env['hr.payslip.run'].browse(self.env.context.get('active_id'))

        if not self.env.context.get('active_id'):
            return super(HrPayslipEmployees, self).compute_sheet()

        employees = self.with_context(active_test=False).employee_ids
        if not employees:
            raise UserError(_("You must select employee(s) to generate payslip(s)."))

        payslips = self.env['hr.payslip']

        for employee in employees:
            # 2. Find the active contract
            contract = employee.contract_ids.sorted('date_start', reverse=True).filtered(
                lambda c: c.state in ['open', 'close'] and
                          (not c.date_end or c.date_end >= payslip_run.date_start)
            )[:1]

            # -------------------------------------------------------------
            # CUSTOM LOGIC
            # -------------------------------------------------------------
            target_structure = False

            # Option A: Check Contract field
            if hasattr(contract, 'structure_id') and contract.structure_id:
                target_structure = contract.structure_id

            # Option B: Fallback - Name Match (CORRECTED)
            # Removed 'company_id' from the domain as it caused the crash
            if not target_structure:
                target_structure = self.env['hr.payroll.structure'].search([
                    ('name', '=', employee.name)
                    # You can add ('country_id', '=', employee.company_id.country_id.id) if needed
                ], limit=1)

            # Option C: Standard Fallback
            if not target_structure:
                target_structure = self.structure_id or contract.structure_type_id.default_struct_id
            # -------------------------------------------------------------

            vals = {
                'employee_id': employee.id,
                'date_from': payslip_run.date_start,
                'date_to': payslip_run.date_end,
                'contract_id': contract.id,
                'struct_id': target_structure.id,
                'payslip_run_id': payslip_run.id,
                'company_id': self.env.company.id,
                'name': '%(payslip_name)s - %(employee_name)s - %(dates)s' % {
                    'payslip_name': _('Payslip'),
                    'employee_name': employee.name,
                    'dates': format_date(self.env, payslip_run.date_start, date_format="MMMM y")
                },
            }
            payslips += self.env['hr.payslip'].create(vals)

        payslips.compute_sheet()

        return {
            'type': 'ir.actions.act_window_close',
        }