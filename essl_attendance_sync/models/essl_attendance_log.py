from odoo import models, fields

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
