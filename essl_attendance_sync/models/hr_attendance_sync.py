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
            - punch_time (Datetime UTC) -> for attendance processing
            - status / error_message for traceability
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

        ist = pytz.timezone("Asia/Kolkata")

        # End: now (IST)
        to_dt_ist = datetime.now(ist)

        # Start: beginning of previous day (IST)
        from_dt_ist = (to_dt_ist - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        # from_dt_ist = ist.localize(datetime(2026, 1, 1, 0, 0, 0))

        from_dt_str = from_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")
        to_dt_str = to_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")

        _logger.info(f"Fetching logs {from_dt_str} → {to_dt_str}")

        all_logs = []
        LogModel = self.env["essl.attendance.log"]
        employee_obj = self.env["hr.employee"]

        # 3. FETCH LOGS FROM DEVICES
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

                log_data_list = (
                    response.get('strDataList')
                    if isinstance(response, dict)
                    else getattr(response, 'strDataList', None)
                )

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

        # 4. PARSE & SAVE RAW LOGS (WITH DEDUP + ERROR INFO)
        inserted = 0
        skipped = 0
        offset = timedelta(hours=5, minutes=30)  # IST offset

        for line in all_logs:
            try:
                parts = line.split("\t")
                if len(parts) < 2:
                    continue

                device_emp_id = parts[0].strip()
                raw_ist_str = parts[1].strip()

                # Dedup check
                exists = LogModel.search_count([
                    ("employee_device_id", "=", device_emp_id),
                    ("punch_time_local", "=", raw_ist_str),
                ])
                if exists:
                    skipped += 1
                    continue

                # Parse IST → UTC
                ist_dt = datetime.strptime(raw_ist_str, "%Y-%m-%d %H:%M:%S")
                utc_dt = ist_dt - offset

                employee = employee_obj.search(
                    [('essl_device_id', '=', device_emp_id)],
                    limit=1
                )

                error_msg = False
                status = False

                if not employee:
                    status = "error"
                    error_msg = "Employee not mapped to eSSL Device ID"

                LogModel.create({
                    "employee_device_id": device_emp_id,
                    "employee_id": employee.id if employee else False,
                    "punch_time_local": raw_ist_str,
                    "punch_time": utc_dt,
                    "raw_line": line,
                    "processed": False,
                    "status": status,
                    "error_message": error_msg,
                })

                inserted += 1

            except Exception as e:
                _logger.error(f"[Parse Error] {line}: {e}")

                # best-effort save of failed log
                try:
                    LogModel.create({
                        "employee_device_id": device_emp_id if 'device_emp_id' in locals() else False,
                        "employee_id": False,
                        "punch_time_local": raw_ist_str if 'raw_ist_str' in locals() else False,
                        "raw_line": line,
                        "processed": True,
                        "status": "error",
                        "error_message": str(e),
                    })
                except Exception:
                    pass

        _logger.info(
            f"eSSL Raw Logs Sync Complete → Inserted: {inserted}, Skipped (duplicates): {skipped}"
        )

    @api.model
    def process_essl_attendance_logs(self):
        Log = self.env["essl.attendance.log"]
        Attendance = self.env["hr.attendance"]
        MAX_NIGHT_SHIFT_HOURS = 14  # Extended slightly for long shifts

        logs = Log.search([
            ("processed", "=", False),
            ("employee_id", "!=", False),
        ], order="employee_id, punch_time asc")

        if not logs:
            return

        logs_by_employee = {}
        for log in logs:
            logs_by_employee.setdefault(log.employee_id.id, []).append(log)

        for emp_id, emp_logs in logs_by_employee.items():
            for log in emp_logs:
                punch_dt = log.punch_time

                # Look for the most recent attendance for this employee
                last_att = Attendance.search([
                    ("employee_id", "=", emp_id)
                ], order="check_in desc", limit=1)

                try:
                    # CASE 1: No previous record or previous record is fully closed
                    # AND it's a new day/shift
                    if not last_att or (last_att.check_out and (
                            punch_dt - last_att.check_in).total_seconds() / 3600 > MAX_NIGHT_SHIFT_HOURS):
                        Attendance.create({
                            "employee_id": emp_id,
                            "check_in": punch_dt,
                        })

                    # CASE 2: Open record exists
                    elif not last_att.check_out:
                        gap = (punch_dt - last_att.check_in).total_seconds() / 3600

                        if gap <= MAX_NIGHT_SHIFT_HOURS:
                            # It's a valid checkout (even if it's the 3rd or 4th punch)
                            last_att.write({"check_out": punch_dt})
                        else:
                            # It's a new day, but the old one was never closed.
                            # Odoo 18 requires a check_out to allow a new check_in.
                            # We "force close" the old one at +1 minute or same time.
                            last_att.write({"check_out": last_att.check_in})
                            Attendance.create({
                                "employee_id": emp_id,
                                "check_in": punch_dt,
                            })

                    # CASE 3: Previous record is closed, but this punch is within the
                    # MAX_NIGHT_SHIFT_HOURS window (Treat as an updated checkout)
                    else:
                        last_att.write({"check_out": punch_dt})

                    log.write({"processed": True, "status": "success"})

                except Exception as e:
                    log.write({"processed": True, "status": "error", "error_message": str(e)})
