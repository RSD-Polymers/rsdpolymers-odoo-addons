from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta, time
import logging

_logger = logging.getLogger(__name__)

# Try to import 'zeep'
try:
    from zeep import Client
    from zeep.exceptions import Fault
except ImportError:
    _logger.warning("The 'zeep' library is not installed. SOAP integration will not work.")
    Client = None

# Try pytz for API date-range formatting
try:
    import pytz
except ImportError:
    _logger.warning("The 'pytz' library is not installed.")
    pytz = None


# ================================
# 1) EXTEND hr.employee
# ================================
class HREmployeeSync(models.Model):
    _inherit = 'hr.employee'

    essl_device_id = fields.Char(
        string="eSSL Device ID",
        copy=False,
        groups="hr.group_hr_user"
    )

    attendance_manager_id = fields.Many2one(
        'res.users',
        string="Attendance Manager",
        groups="hr_attendance.group_hr_attendance_officer",
        help="User responsible for attendance corrections.",
    )


# ================================
# 2) EXTEND hr.attendance
# (METHOD NAMES UNCHANGED)
# ================================
class HRAttendanceCronMethods(models.Model):
    _inherit = 'hr.attendance'

    # -------------------------------------------------------
    # KEEP METHOD NAME AS IS, BUT NOW IT *DOES NOTHING*
    # (We will not use this anymore. Processing handled later.)
    # -------------------------------------------------------
    def _create_or_update_attendance(self, parsed_punches, extend_tolerance_minutes=10):
        """
        Deprecated in new design.
        Raw punches are NOT processed here anymore.
        """
        _logger.info("Skipping attendance creation. New design imports raw logs only.")
        return True

    # -------------------------------------------------------
    # MAIN CRON — NOW ONLY IMPORTS RAW LOGS INTO CUSTOM MODEL
    # -------------------------------------------------------
    @api.model
    def sync_essl_attendance_logs(self):
        """
        Fetches attendance logs from eSSL devices and stores them ONLY in the custom raw log model.
        Does NOT create hr.attendance records here.
        Stores:
            - punch_time_local (Char) -> raw IST from device
            - punch_time (UTC) -> converted UTC datetime
        """
        if not Client:
            raise UserError(_("The 'zeep' library is required but not installed on the Odoo server."))

        _logger.info("--- Starting eSSL Attendance Synchronization ---")

        # 1. READ CONFIG
        config_param = self.env['ir.config_parameter'].sudo()
        wsdl_url = config_param.get_param('essl_attendance_sync.wsdl_url')
        username = config_param.get_param('essl_attendance_sync.username')
        password = config_param.get_param('essl_attendance_sync.password')
        serial_numbers_str = config_param.get_param('essl_attendance_sync.serial_number', '')

        serial_numbers = [s.strip() for s in serial_numbers_str.split(',') if s.strip()]
        if not all([wsdl_url, username, password]) or not serial_numbers:
            _logger.error("Missing configuration for eSSL sync.")
            return

        # 2. DATE RANGE (use UTC internally)
        server_now = datetime.now()
        days_to_sync = 11
        to_datetime = (server_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        from_datetime = to_datetime - timedelta(days=days_to_sync)

        if pytz:
            ist = pytz.timezone('Asia/Kolkata')
            from_dt_ist = pytz.utc.localize(from_datetime).astimezone(ist)
            to_dt_ist = pytz.utc.localize(to_datetime).astimezone(ist)
            from_dt_str = from_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")
            to_dt_str = to_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            from_dt_str = from_datetime.strftime("%Y-%m-%dT%H:%M:%S")
            to_dt_str = to_datetime.strftime("%Y-%m-%dT%H:%M:%S")

        _logger.info(f"Fetching logs {from_dt_str} → {to_dt_str}")

        all_logs = []
        LogModel = self.env["essl.attendance.log"]

        # 3. FETCH LOGS FROM ALL DEVICES
        for serial_number in serial_numbers:
            try:
                client = Client(wsdl_url)
                response = client.service.GetTransactionsLog(
                    FromDateTime=from_dt_str,
                    ToDateTime=to_dt_str,
                    SerialNumber=serial_number,
                    UserName=username,
                    UserPassword=password,
                    strDataList=''
                )

                log_data_list = response.get('strDataList') if isinstance(response, dict) else getattr(response,
                                                                                                       'strDataList',
                                                                                                       None)

                if not log_data_list:
                    _logger.warning(f"No logs from device {serial_number}")
                    continue

                if log_data_list == 'Unathorised User':
                    _logger.error(f"Unauthorized for device {serial_number}")
                    continue

                logs = log_data_list.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                logs = [l.strip() for l in logs if l.strip()]
                all_logs.extend(logs)

                _logger.info(f"Fetched {len(logs)} logs from device {serial_number}")

            except Exception as e:
                _logger.error(f"Error fetching logs from {serial_number}: {e}")

        if not all_logs:
            _logger.info("No logs received.")
            return

        # 4. PARSE & SAVE RAW LOGS
        employee_obj = self.env['hr.employee']
        processed = 0
        offset = timedelta(hours=5, minutes=30)  # IST offset

        skipped = 0

        for line in all_logs:
            try:
                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                device_emp_id = parts[0].strip()
                raw_ist_str = parts[1].strip()  # IST string from device

                exists = LogModel.search_count([
                    ("employee_device_id", "=", device_emp_id),
                    ("punch_time_local", "=", raw_ist_str),
                ])

                if exists:
                    skipped += 1
                    continue

                # Parse raw IST to datetime
                ist_dt = datetime.strptime(raw_ist_str, "%Y-%m-%d %H:%M:%S")

                # Convert IST→UTC
                utc_dt = ist_dt - offset

                # Detect employee
                employee = employee_obj.search([('essl_device_id', '=', device_emp_id)], limit=1)

                # Store raw IST (Char) and UTC datetime
                LogModel.create({
                    "employee_device_id": device_emp_id,
                    "employee_id": employee.id if employee else False,
                    "punch_time_local": raw_ist_str,  # EXACT from device
                    "punch_time": utc_dt,  # for attendance processing later
                    "raw_line": line,
                    "processed": False,
                })

                processed += 1

            except Exception as e:
                _logger.error(f"[Parse Error] {line}: {e}")

        _logger.info(
            f"eSSL Raw Logs Sync Complete → Inserted: {processed}, Skipped (duplicates): {skipped}"
        )

    @api.model
    def process_essl_attendance_logs(self):
        """
        Reads all unprocessed raw logs from essl.attendance.log,
        applies Option A logic (one attendance per day),
        supports night shift (20:00 → 08:00),
        and creates/updates hr.attendance.
        """

        Log = self.env["essl.attendance.log"]
        Employee = self.env["hr.employee"]
        Attendance = self.env["hr.attendance"]

        # Fetch unprocessed logs
        logs = Log.search([("processed", "=", False)], order="punch_time_local asc")

        if not logs:
            _logger.info("No unprocessed eSSL logs found.")
            return

        # Group punches by employee → by local date (IST)
        punches = {}  # punches[employee_id][date] = list of datetimes

        for log in logs:
            try:
                emp_id = log.employee_id.id
                if not emp_id:
                    log.status = "error"
                    log.error_message = "Employee not mapped to eSSL Device ID"
                    log.processed = True
                    continue

                punch_dt = log.punch_time  # IST datetime

                # Determine "logical attendance date" (handles night shift)
                punch_dt_ist = punch_dt + timedelta(hours=5, minutes=30)
                punch_date = punch_dt_ist.date()

                # Build grouping structure
                punches.setdefault(emp_id, {})
                punches[emp_id].setdefault(punch_date, [])
                punches[emp_id][punch_date].append((log, punch_dt))

            except Exception as e:
                _logger.error(f"Error grouping log {log.id}: {e}")
                log.status = "error"
                log.error_message = f"Grouping failed: {e}"
                log.processed = True

        night_start = time(20, 0)  # 08:00 PM
        night_end = time(8, 0)  # 08:00 AM

        # Process each employee
        for emp_id, emp_days in punches.items():

            # Sort days chronologically
            for punch_date in sorted(emp_days.keys()):
                day_punches = emp_days[punch_date]

                # Sort punches within the day
                day_punches.sort(key=lambda x: x[1])

                first_log, first_dt = day_punches[0]
                last_log, last_dt = day_punches[-1]

                # ----------------------------
                # NIGHT SHIFT CHECK
                # ----------------------------
                # If this is early morning (<8am), check if yesterday had a night punch
                if first_dt.time() <= night_end:

                    prev_date = punch_date - timedelta(days=1)

                    # Get yesterday punches if any
                    prev_logs = punches.get(emp_id, {}).get(prev_date, [])
                    if prev_logs:
                        # Check last punch of previous day
                        prev_last_log, prev_last_dt = sorted(prev_logs, key=lambda x: x[1])[-1]

                        # Night-shift logic:
                        if prev_last_dt.time() >= night_start:
                            # Extend previous day's attendance

                            prev_att = Attendance.search([
                                ("employee_id", "=", emp_id),
                                ("check_in", ">=", datetime.combine(prev_date, time(0, 0, 0))),
                                ("check_in", "<=", datetime.combine(prev_date, time(23, 59, 59))),
                            ], limit=1)

                            if prev_att:
                                prev_att.check_out = last_dt
                            else:
                                # Create new night attendance
                                Attendance.create({
                                    "employee_id": emp_id,
                                    "check_in": prev_last_dt,
                                    "check_out": last_dt,
                                })

                            # Mark today's logs as processed
                            for log, _dt in day_punches:
                                log.status = "success"
                                log.processed = True

                            continue  # DO NOT create a new attendance day record

                # ----------------------------
                # NORMAL DAY — OPTION A LOGIC
                # ----------------------------
                existing_att = Attendance.search([
                    ("employee_id", "=", emp_id),
                    ("check_in", ">=", datetime.combine(punch_date, time(0, 0, 0))),
                    ("check_in", "<=", datetime.combine(punch_date, time(23, 59, 59))),
                ], limit=1)

                if existing_att:
                    # Extend end time
                    if last_dt > (existing_att.check_out or existing_att.check_in):
                        existing_att.check_out = last_dt
                else:
                    # Create new attendance record
                    Attendance.create({
                        "employee_id": emp_id,
                        "check_in": first_dt,
                        "check_out": last_dt,
                    })

                # Mark all logs of that day as processed
                for log, _dt in day_punches:
                    log.status = "success"
                    log.processed = True

        _logger.info("eSSL Attendance Processing Completed Successfully.")