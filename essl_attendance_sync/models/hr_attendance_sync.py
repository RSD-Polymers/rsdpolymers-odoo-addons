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
        """
        Process raw eSSL logs into hr.attendance

        Rules:
        - Night shift supported (20:00 → 08:00)
        - Single punch => attendance with check_in only (Option A)
        - No silent skipping
        """

        Log = self.env["essl.attendance.log"]
        Attendance = self.env["hr.attendance"]

        night_end = time(8, 0)  # 08:00 AM

        logs = Log.search(
            [("processed", "=", False)],
            order="punch_time asc"
        )

        if not logs:
            _logger.info("No unprocessed logs found.")
            return

        # punches[employee_id][attendance_date] = [(log, datetime)]
        punches = {}

        # -------------------------------------------------
        # 1️⃣ GROUP LOGS BY *LOGICAL ATTENDANCE DATE*
        # -------------------------------------------------
        for log in logs:
            try:
                if not log.employee_id:
                    log.status = "error"
                    log.error_message = "Employee not mapped"
                    continue

                punch_dt = log.punch_time
                punch_time = punch_dt.time()

                # Night-shift date logic
                if punch_time <= night_end:
                    attendance_date = punch_dt.date() - timedelta(days=1)
                else:
                    attendance_date = punch_dt.date()

                emp_id = log.employee_id.id

                punches.setdefault(emp_id, {})
                punches[emp_id].setdefault(attendance_date, [])
                punches[emp_id][attendance_date].append((log, punch_dt))

            except Exception as e:
                log.status = "error"
                log.error_message = f"Grouping error: {e}"

        # -------------------------------------------------
        # 2️⃣ CREATE / UPDATE ATTENDANCE
        # -------------------------------------------------
        for emp_id, emp_days in punches.items():
            for att_date, records in emp_days.items():
                try:
                    records.sort(key=lambda r: r[1])
                    dts = [dt for _, dt in records]

                    first_dt = dts[0]
                    last_dt = dts[-1]

                    attendance = Attendance.search([
                        ("employee_id", "=", emp_id),
                        ("check_in", ">=", datetime.combine(att_date, time.min)),
                        ("check_in", "<=", datetime.combine(att_date, time.max)),
                    ], limit=1)

                    # ------------------------------------
                    # OPTION A — SINGLE PUNCH
                    # ------------------------------------
                    if len(dts) == 1:
                        if not attendance:
                            Attendance.create({
                                "employee_id": emp_id,
                                "check_in": first_dt,
                                "check_out": False,
                            })

                        for log, _ in records:
                            log.status = "success"
                            log.error_message = "Single punch (missing check-out)"
                            log.processed = True

                        continue

                    # ------------------------------------
                    # NORMAL IN / OUT
                    # ------------------------------------
                    if attendance:
                        attendance.check_out = max(
                            attendance.check_out or first_dt,
                            last_dt
                        )
                    else:
                        Attendance.create({
                            "employee_id": emp_id,
                            "check_in": first_dt,
                            "check_out": last_dt,
                        })

                    for log, _ in records:
                        log.status = "success"
                        log.error_message = False
                        log.processed = True

                except Exception as e:
                    for log, _ in records:
                        log.status = "error"
                        log.error_message = f"Attendance creation failed: {e}"

        _logger.info("eSSL attendance processing completed successfully.")


