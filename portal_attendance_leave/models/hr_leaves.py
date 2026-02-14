from datetime import datetime, timedelta
import logging
import pytz
from pytz import timezone, UTC

from odoo.exceptions import ValidationError
from odoo.tools import float_compare
from odoo.tools.translate import _
from odoo import api, Command, fields, models, tools


_logger = logging.getLogger(__name__)



class HrLeaves(models.Model):
    _inherit='hr.leave'

    is_concession_leave = fields.Boolean(
        compute="_compute_is_concession_leave",
        store=False
    )

    @api.depends("holiday_status_id")
    def _compute_is_concession_leave(self):
        for rec in self:
            name = rec.holiday_status_id.display_name or ""
            rec.is_concession_leave = "Concession" in name

    def _validate_leave_request(self):
        """ Validate time off requests
        by creating a calendar event and a resource time off. """
        holidays = self.filtered("employee_id")
        holidays._create_resource_leave()
        meeting_holidays = holidays.filtered(lambda l: l.holiday_status_id.create_calendar_meeting)
        meetings = self.env['calendar.event']
        if meeting_holidays:
            meeting_values_for_user_id = meeting_holidays._prepare_holidays_meeting_values()
            Meeting = self.env['calendar.event']
            for user_id, meeting_values in meeting_values_for_user_id.items():
                meetings += Meeting.with_user(user_id or self.env.uid).with_context(
                                allowed_company_ids=[],
                                no_mail_to_attendees=True,
                                calendar_no_videocall=True,
                                active_model=self._name
                            ).sudo().create(meeting_values)
        Holiday = self.env['hr.leave']
        for meeting in meetings:
            Holiday.browse(meeting.res_id).meeting_id = meeting

        for holiday in holidays:
            user_tz = timezone(holiday.tz)
            utc_tz = pytz.utc.localize(holiday.date_from).astimezone(user_tz)
            notify_partner_ids = holiday.employee_id.user_id.partner_id.ids
            holiday.message_post(
                body=_(
                    'Your %(leave_type)s planned on %(date)s has been accepted',
                    leave_type=holiday.holiday_status_id.display_name,
                    date=utc_tz.replace(tzinfo=None)
                ),
                partner_ids=notify_partner_ids)

    @api.constrains("holiday_status_id", "request_hour_from", "request_hour_to", "employee_id", "request_date_from")
    def _check_concession_limit(self):
        # fetch concession leave type once
        concession_type = self.env["hr.leave.type"].search([
            ("name", "=", "Concession - (Late Coming & Early Going)")
        ], limit=1)

        for leave in self:
            if leave.holiday_status_id != concession_type:
                continue

            if not leave.request_hour_from or not leave.request_hour_to:
                continue

            duration = leave.request_hour_to - leave.request_hour_from

            # --- max 1 hour ---
            if float_compare(duration, 1.0, precision_digits=2) == 1:
                raise ValidationError(
                    "Only 1 hour concession allowed.\n"
                    "Please apply for Half Day leave."
                )

            # --- max 3 per month ---
            start = leave.request_date_from
            month_start = start.replace(day=1)

            if start.month == 12:
                month_end = start.replace(day=31)
            else:
                month_end = start.replace(month=start.month + 1, day=1)

            existing = self.search([
                ("employee_id", "=", leave.employee_id.id),
                ("holiday_status_id", "=", concession_type.id),
                ("request_date_from", ">=", month_start),
                ("request_date_from", "<", month_end),
                ("state", "in", ["confirm", "validate1", "validate"]),
                ("id", "!=", leave.id),
            ])

            if len(existing) >= 3:
                raise ValidationError(
                    "Monthly concession limit exceeded.\n"
                    "Please apply for Half Day leave."
                )

    def _validate_comp_off_day(self, employee, work_date, leave_type):
        """Reusable validation for backend + portal"""

        comp_off_types = ['Comp Off', 'Comp Off (PAPL)']
        od_type_names = ['Out Duty', 'OD']

        if leave_type.name not in comp_off_types:
            return True

        formatted_date = work_date.strftime('%d-%m-%Y')
        calendar = employee.resource_calendar_id

        if not calendar:
            raise ValidationError(_("Employee has no working schedule."))

        # --------------------------------------------------
        # 1️⃣ Approved OD (allowed on ANY day)
        # --------------------------------------------------
        od_leave = self.env['hr.leave'].search([
            ('employee_id', '=', employee.id),
            ('state', '=', 'validate'),
            ('holiday_status_id.name', 'in', od_type_names),
            ('request_date_from', '<=', work_date),
            ('request_date_to', '>=', work_date),
        ], limit=1)

        if od_leave:
            return True

        # --------------------------------------------------
        # 2️⃣ Weekly off / public holiday check
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
        # 3️⃣ Attendance check
        # --------------------------------------------------
        attendance = self.env['hr.attendance'].search([
            ('employee_id', '=', employee.id),
            ('check_in', '>=', work_date),
            ('check_in', '<', work_date + timedelta(days=1))
        ], limit=1)

        if not attendance:
            raise ValidationError(
                _("No attendance or approved Out Duty found.")
            )

        return True

    @api.onchange('request_hour_from', 'holiday_status_id')
    def _onchange_concession_auto_to(self):
        for rec in self:
            if rec.is_concession_leave and rec.request_hour_from:
                rec.request_hour_to = rec.request_hour_from + 1.0

    def _check_working_hours(self):
        normal = self.filtered(lambda l: not l.holiday_status_id.is_out_duty)
        if normal:
            return super(HrLeaves, normal)._check_working_hours()
        return True

    def _compute_duration(self):
        super()._compute_duration()

        for leave in self:
            if not leave.holiday_status_id:
                continue

            # 🟢 OUT DUTY
            if leave.holiday_status_id.is_out_duty:
                if leave.request_date_from and leave.request_date_to:
                    delta = (leave.request_date_to - leave.request_date_from).days + 1
                    leave.number_of_days = float(delta)

            # 🟢 COMP OFF AGAINST OD
            if leave.holiday_status_id.is_od_comp_off:
                if leave.request_date_from and leave.request_date_to:
                    delta = (leave.request_date_to - leave.request_date_from).days + 1
                    leave.number_of_days = float(delta)

                    # optional but recommended
                    leave.number_of_hours = delta * (
                            leave.employee_id.resource_calendar_id.hours_per_day or 8
                    )

    def _has_od_for_date(self, employee_id, date):
        if not employee_id or not date:
            return False

        return bool(self.env['hr.leave'].search_count([
            ('employee_id', '=', employee_id),
            ('state', '=', 'validate'),
            ('holiday_status_id.is_out_duty', '=', True),
            ('request_date_from', '<=', date),
            ('request_date_to', '>=', date),
        ]))

    @api.onchange('request_date_from', 'employee_id')
    def _onchange_filter_comp_od(self):
        if not self.employee_id or not self.request_date_from:
            return

        has_od = self._has_od_for_date(self.employee_id.id, self.request_date_from)

        if has_od:
            domain = []
        else:
            domain = [('is_comp_off_od', '=', False)]

        return {
            'domain': {
                'holiday_status_id': domain
            }
        }

    def _check_date(self):
        if self.env.context.get("skip_od_overlap"):
            return super()._check_date()

        for leave in self:
            if leave.holiday_status_id.is_od_comp_off:
                has_od = self.env["hr.leave"].search_count([
                    ("employee_id", "=", leave.employee_id.id),
                    ("state", "=", "validate"),
                    ("holiday_status_id.is_out_duty", "=", True),
                    ("request_date_from", "<=", leave.request_date_from),
                    ("request_date_to", ">=", leave.request_date_from),
                ]) > 0

                if has_od:
                    # allow overlap with OD
                    return

        return super()._check_date()

