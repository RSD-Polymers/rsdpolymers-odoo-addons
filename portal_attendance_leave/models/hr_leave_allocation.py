from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    # 1. Helper field to use in XML "invisible" conditions
    holiday_status_id_name = fields.Char(related='holiday_status_id.name', string='Time Off Type Name')

    # 2. Your custom field
    worked_date = fields.Date(string='Date Worked', help="The holiday/weekend date worked.")

    @api.constrains('worked_date', 'holiday_status_id')
    def _check_attendance_for_comp_off(self):
        comp_off_types = ['Comp Off', 'Comp Off (PAPL)']
        for rec in self:
            if rec.holiday_status_id.name in comp_off_types and rec.worked_date:
                # Search for attendance
                attendance = self.env['hr.attendance'].search([
                    ('employee_id', '=', rec.employee_id.id),
                    ('check_in', '>=', rec.worked_date),
                    ('check_in', '<', rec.worked_date + timedelta(days=1))
                ])
                if not attendance:
                    raise ValidationError(
                        _("No attendance found for %s on %s.") % (rec.employee_id.name, rec.worked_date))

    @api.onchange('worked_date')
    def _onchange_worked_date(self):
        if self.worked_date:
            self.date_from = self.worked_date
            self.date_to = self.worked_date + timedelta(days=45)