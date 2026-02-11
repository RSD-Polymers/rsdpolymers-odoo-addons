from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta, datetime


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    # 1. Helper field to use in XML "invisible" conditions
    holiday_status_id_name = fields.Char(related='holiday_status_id.name', string='Time Off Type Name')

    # 2. Your custom field
    worked_date = fields.Date(string='Date Worked', help="The holiday/weekend date worked.")

    from odoo import api, _
    from odoo.exceptions import ValidationError
    from datetime import timedelta, datetime

    @api.constrains('worked_date', 'holiday_status_id', 'employee_id')
    def _check_attendance_for_comp_off(self):

        comp_off_types = ['Comp Off', 'Comp Off (PAPL)']
        od_type_names = ['Out Duty', 'OD']  # adjust if needed

        for rec in self:
            if rec.holiday_status_id.name not in comp_off_types or not rec.worked_date:
                continue

            employee = rec.employee_id
            work_date = rec.worked_date
            formatted_date = work_date.strftime('%d-%m-%Y')

            calendar = employee.resource_calendar_id
            if not calendar:
                raise ValidationError(_("Employee has no working schedule."))

            # --------------------------------------------------
            # 1️⃣ Check approved OD (OD can be on ANY day)
            # --------------------------------------------------
            od_leave = self.env['hr.leave'].search([
                ('employee_id', '=', employee.id),
                ('state', '=', 'validate'),
                ('holiday_status_id.name', 'in', od_type_names),
                ('request_date_from', '<=', work_date),
                ('request_date_to', '>=', work_date),
            ], limit=1)

            # If OD exists → allow comp off immediately
            if od_leave:
                continue

            # --------------------------------------------------
            # 2️⃣ If no OD → must be weekly off or holiday
            # --------------------------------------------------
            weekday = str(work_date.weekday())
            working_day = self.env['resource.calendar.attendance'].search([
                ('calendar_id', '=', calendar.id),
                ('dayofweek', '=', weekday)
            ], limit=1)

            is_weekly_off = not bool(working_day)

            holiday = self.env['resource.calendar.leaves'].search([
                ('calendar_id', '=', calendar.id),
                ('date_from', '<=', datetime.combine(work_date, datetime.max.time())),
                ('date_to', '>=', datetime.combine(work_date, datetime.min.time()))
            ], limit=1)

            is_public_holiday = bool(holiday)

            if not is_weekly_off and not is_public_holiday:
                raise ValidationError(
                    _("Comp Off can only be applied for Weekly Off or Public Holiday.\n"
                      "Date %s is a working day.") % formatted_date
                )

            # --------------------------------------------------
            # 3️⃣ Check attendance
            # --------------------------------------------------
            attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', employee.id),
                ('check_in', '>=', work_date),
                ('check_in', '<', work_date + timedelta(days=1))
            ], limit=1)

            if not attendance:
                raise ValidationError(
                    _("No attendance or approved Out Duty found for %s on %s.")
                    % (employee.name, formatted_date)
                )

    @api.onchange('worked_date')
    def _onchange_worked_date(self):
        if self.worked_date:
            self.date_from = self.worked_date
            self.date_to = self.worked_date + timedelta(days=45)