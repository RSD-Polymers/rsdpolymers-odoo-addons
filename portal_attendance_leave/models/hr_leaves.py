import logging
import pytz
from pytz import timezone, UTC

from odoo.exceptions import ValidationError
from odoo.tools.translate import _
from odoo import api, Command, fields, models, tools


_logger = logging.getLogger(__name__)



class HrLeaves(models.Model):
    _inherit='hr.leave'

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
            if duration > 1:
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