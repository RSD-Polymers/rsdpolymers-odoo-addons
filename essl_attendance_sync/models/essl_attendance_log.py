from odoo import models, fields, api
from datetime import timedelta

import logging

_logger = logging.getLogger(__name__)

class EsslAttendanceLog(models.Model):
    _name = "essl.attendance.log"
    _description = "Raw eSSL Attendance Logs"
    _order = "punch_time_local asc"
    _rec_name = "employee_device_id"

    employee_device_id = fields.Char(string="eSSL Device ID")
    employee_id = fields.Many2one("hr.employee", string="Employee")
    punch_time_local = fields.Char(string="Punch Time (Local IST)")
    punch_time = fields.Datetime(string="Punch Time (UTC)", help="Converted UTC timestamp for attendance processing")
    raw_line = fields.Char("Raw Line")
    processed = fields.Boolean(default=False)
    process_date = fields.Datetime()
    status = fields.Selection([
        ("success", "Success"),
        ("error", "Error"),
    ])
    error_message = fields.Text(string="Error Message")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            "uniq_device_punch",
            "unique(employee_device_id, punch_time_local)",
            "This punch already exists for this device and time."
        )
    ]

    @api.model
    def cron_archive_old_logs(self):
        """Archive logs older than 30 days (runs daily)"""

        cutoff_date = fields.Datetime.now() - timedelta(days=30)

        domain = [
            ('punch_time', '<', cutoff_date),
            ('active', '=', True)
        ]

        batch_size = 1000
        total_archived = 0

        while True:
            logs = self.search(domain, limit=batch_size)
            if not logs:
                break

            logs.write({'active': False})
            total_archived += len(logs)

        _logger.info("Archived %s eSSL attendance logs older than 30 days", total_archived)
