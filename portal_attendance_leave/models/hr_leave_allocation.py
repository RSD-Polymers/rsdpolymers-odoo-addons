from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import timedelta, datetime


class HrLeaveAllocation(models.Model):
    _inherit = 'hr.leave.allocation'

    # 1. Helper field to use in XML "invisible" conditions
    holiday_status_id_name = fields.Char(related='holiday_status_id.name', string='Time Off Type Name')

    worked_date = fields.Date(string='Date Worked', help="The holiday/weekend date worked.")

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

    def _set_validity_from_worked_date(self, vals):
        """Set validity = worked_date + 45 days"""

        leave_type = None

        if vals.get('holiday_status_id'):
            leave_type = self.env['hr.leave.type'].browse(vals['holiday_status_id'])

        # -------------------------------------------------
        # CASE 1: CREATE → self is empty → use vals only
        # -------------------------------------------------
        if not self:
            lt = leave_type
            worked_date = vals.get('worked_date')

            if lt and lt.name in ['Comp Off', 'Comp Off (PAPL)'] and worked_date:
                worked_date = fields.Date.to_date(worked_date)

                vals['date_from'] = worked_date
                vals['date_to'] = worked_date + timedelta(days=45)

            return vals

        # -------------------------------------------------
        # CASE 2: WRITE → self has records
        # -------------------------------------------------
        for rec in self:
            lt = leave_type or rec.holiday_status_id

            if not lt:
                continue

            if lt.name not in ['Comp Off', 'Comp Off (PAPL)']:
                continue

            worked_date = vals.get('worked_date') or rec.worked_date
            if not worked_date:
                continue

            worked_date = fields.Date.to_date(worked_date)

            vals['date_from'] = worked_date
            vals['date_to'] = worked_date + timedelta(days=45)

        return vals

    @api.model
    def create(self, vals):
        vals = self._set_validity_from_worked_date(vals)
        return super().create(vals)

    def write(self, vals):
        vals = self._set_validity_from_worked_date(vals)
        return super().write(vals)