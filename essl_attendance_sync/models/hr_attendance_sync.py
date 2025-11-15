from odoo import models, fields, api, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

# Try to import 'zeep'
try:
    from zeep import Client
    from zeep.exceptions import Fault
except ImportError:
    _logger.warning("The 'zeep' library is not installed. SOAP integration will not work.")
    Client = None  # Dummy assignment for safety

# Try to import 'pytz' for timezone conversion
try:
    import pytz
except ImportError:
    _logger.warning("The 'pytz' library is not installed. Timezone handling may be incorrect. Install pytz!")
    pytz = None


# --- 1. Inheritance for hr.employee (Adds the mapping field) ---
class HREmployeeSync(models.Model):
    _inherit = 'hr.employee'

    # Add a field to hr.employee to map to the biometric device's Employee ID
    essl_device_id = fields.Char(string="eSSL Device ID", copy=False, groups="hr.group_hr_user")

    attendance_manager_id = fields.Many2one(
        'res.users',
        string="Attendance Manager",
        groups="hr_attendance.group_hr_attendance_officer",  # 👈 add officer group here
        help="The user set in Attendance will access the attendance of the employee "
             "through the dedicated app and will be able to edit them.",
    )

# --- 2. Inheritance for hr.attendance (Hosts the Cron Job function) ---
class HRAttendanceCronMethods(models.Model):
    _inherit = 'hr.attendance'

    def _create_or_update_attendance(self, parsed_punches):
        """
        Processes parsed punches to create or update hr.attendance records.
        A basic logic for handling check-in/check-out pairs based on time sequence.
        """
        # 1. Group punches by employee
        punches_by_employee = {}
        for punch in parsed_punches:
            employee_id = punch['employee_id']
            if employee_id not in punches_by_employee:
                punches_by_employee[employee_id] = []
            punches_by_employee[employee_id].append(punch)

        # 2. Process each employee's punches
        for employee_id, punches in punches_by_employee.items():

            # Sort punches chronologically
            punches.sort(key=lambda p: p['punch_time'])
            employee = self.env['hr.employee'].browse(employee_id)

            # Get the single, latest open attendance record *before* starting the loop.
            last_attendance = self.env['hr.attendance'].search([
                ('employee_id', '=', employee_id),
                ('check_out', '=', False)
            ], limit=1, order='check_in DESC')

            for punch in punches:

                # Check 1: If an attendance record is currently open (Check-in state), this punch must be the Check-out.
                if last_attendance:

                    # Safety check: Ensure the punch is after the existing check-in time
                    if punch['punch_time'] <= last_attendance.check_in:
                        _logger.warning(
                            f"Skipping punch for {employee.name} at {punch['punch_time']}: Punch time is before existing open check-in. Likely a skipped check-out or duplicate log.")
                        continue

                    # Write the check-out time
                    last_attendance.write({'check_out': punch['punch_time']})
                    _logger.info(f"Updated attendance for {employee.name}: Check-out at {punch['punch_time']}")
                    last_attendance = False  # Attendance is now closed

                # Check 2: If no attendance is open, this punch must be a new Check-in.
                else:
                    # CRITICAL FIX for re-runs: Check if a Check-in record for this EXACT time already exists.
                    existing_check_in = self.env['hr.attendance'].search([
                        ('employee_id', '=', employee_id),
                        ('check_in', '=', punch['punch_time']),
                    ], limit=1)

                    if existing_check_in:
                        # Found an existing check-in record for this exact time. Skip this punch.
                        _logger.info(
                            f"Skipping punch for {employee.name} at {punch['punch_time']}: Check-in record already exists, preventing duplicate creation.")

                        # IMPORTANT: If the existing record is OPEN, we must reset last_attendance to it
                        # so the next punch can close it (handles cases where a previous run failed mid-update).
                        if not existing_check_in.check_out:
                            last_attendance = existing_check_in
                            _logger.info(
                                f"Setting last_attendance for {employee.name} to existing open record at {existing_check_in.check_in}.")

                        continue

                    # Final flow: Create the new Check-in.
                    new_attendance = self.create({
                        'employee_id': employee_id,
                        'check_in': punch['punch_time'],
                        'check_out': False,
                    })
                    _logger.info(f"Created attendance for {employee.name}: Check-in at {punch['punch_time']}")
                    last_attendance = new_attendance  # Set the newly created record as the open one

        return True

    @api.model
    @api.model
    def sync_essl_attendance_logs(self):
        """
        Fetches attendance logs from all configured eSSL devices and creates Odoo hr.attendance records.
        Supports multiple devices by reading comma-separated serial numbers from Odoo config.
        """
        if not Client:
            raise UserError(_("The 'zeep' library is required but not installed on the Odoo server."))

        _logger.info("--- Starting eSSL Attendance Synchronization ---")

        # 1. READ CONFIGURATIONS
        config_param = self.env['ir.config_parameter'].sudo()
        wsdl_url = config_param.get_param('essl_attendance_sync.wsdl_url')
        username = config_param.get_param('essl_attendance_sync.username')
        password = config_param.get_param('essl_attendance_sync.password')
        serial_numbers_str = config_param.get_param('essl_attendance_sync.serial_number', '')

        serial_numbers = [s.strip() for s in serial_numbers_str.split(',') if s.strip()]
        if not all([wsdl_url, username, password]) or not serial_numbers:
            _logger.error("eSSL synchronization failed: Missing configuration parameters or Serial Numbers.")
            return

        # 2. CALCULATE DATE RANGE (Last N FULL Days, Converted to IST for API)
        server_now_utc = datetime.now()
        days_to_sync = 3
        to_datetime_utc = server_now_utc + timedelta(days=1)
        to_datetime_utc = to_datetime_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        from_datetime_utc = to_datetime_utc - timedelta(days=days_to_sync)

        if pytz:
            ist_tz = pytz.timezone('Asia/Kolkata')
            from_dt_ist = pytz.utc.localize(from_datetime_utc, is_dst=None).astimezone(ist_tz)
            to_dt_ist = pytz.utc.localize(to_datetime_utc, is_dst=None).astimezone(ist_tz)
            from_dt_str = from_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")
            to_dt_str = to_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            from_dt_str = from_datetime_utc.strftime("%Y-%m-%dT%H:%M:%S")
            to_dt_str = to_datetime_utc.strftime("%Y-%m-%dT%H:%M:%S")

        _logger.info(f"Syncing logs from {from_dt_str} to {to_dt_str} (Last {days_to_sync} full days)")

        all_logs = []

        # 3. LOOP THROUGH ALL SERIAL NUMBERS
        for serial_number in serial_numbers:
            _logger.info(f"Fetching logs from device: {serial_number}")
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

                if isinstance(response, dict):
                    log_data_list = response.get('strDataList')
                else:
                    log_data_list = getattr(response, 'strDataList', None)

                if not log_data_list:
                    _logger.warning(f"No logs returned from device {serial_number}. Skipping.")
                    continue
                if log_data_list == 'Unathorised User':
                    _logger.error(f"Unauthorized access for device {serial_number}. Check credentials.")
                    continue

                logs = log_data_list.replace('\r\n', '\n').replace('\r', '\n').split('\n')
                logs = [line.strip() for line in logs if line.strip()]
                all_logs.extend(logs)
                _logger.info(f"Fetched {len(logs)} logs from device {serial_number}")

            except Fault as e:
                _logger.error(f"SOAP Fault while fetching logs from device {serial_number}: {e}")
            except Exception as e:
                _logger.error(f"Error fetching logs from device {serial_number}: {e}")

        if not all_logs:
            _logger.info("No attendance logs found from any devices. Exiting sync.")
            return

        # 4. AUTO-CLOSE STALE OPEN ATTENDANCES BEFORE PROCESSING NEW LOGS
        try:
            stale_threshold = datetime.now() - timedelta(hours=16)
            stale_open_attendances = self.env['hr.attendance'].search([
                ('check_out', '=', False),
                ('check_in', '<', stale_threshold)
            ])
            _logger.info(f"Found {len(stale_open_attendances)} stale open attendances to auto-close.")

            for attendance in stale_open_attendances:
                close_time = attendance.check_in.replace(hour=23, minute=59, second=59)
                attendance.write({'check_out': close_time})
                _logger.info(f"Auto-closed stale attendance for {attendance.employee_id.name} "
                             f"from {attendance.check_in} → {close_time}.")
        except Exception as e:
            _logger.error(f"Error auto-closing stale attendances: {e}")

        # 5. PARSE ALL LOGS
        parsed_punches = []
        employee_obj = self.env['hr.employee']
        processed_logs_count = 0

        for log_line in all_logs:
            if not log_line:
                continue
            try:
                fields_data = log_line.strip().split('\t')
                if len(fields_data) < 2:
                    _logger.warning(f"Skipping malformed log: {log_line}")
                    continue

                employee_device_id = fields_data[0]
                punch_time_str = fields_data[1].strip()
                punch_status = '0'
                punch_datetime = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")

                punch_time_utc = punch_datetime
                if pytz:
                    ist = pytz.timezone('Asia/Kolkata')
                    local_punch_datetime = ist.localize(punch_datetime, is_dst=None)
                    punch_time_utc = local_punch_datetime.astimezone(pytz.utc).replace(tzinfo=None)

                employee = employee_obj.search([('essl_device_id', '=', employee_device_id)], limit=1)
                if not employee:
                    _logger.warning(
                        f"No Odoo Employee found for Device ID: {employee_device_id}. Skipping punch at {punch_time_str}.")
                    continue

                parsed_punches.append({
                    'employee_id': employee.id,
                    'punch_time': punch_time_utc,
                    'is_checkout': punch_status == '1',
                })
                processed_logs_count += 1

            except ValueError:
                _logger.error(f"Date/Time format error in log: {log_line}. Expected YYYY-MM-DD HH:MM:SS.")
            except Exception as e:
                _logger.error(f"Error processing log line: {log_line}. Error: {e}")

        _logger.info(f"Successfully parsed {processed_logs_count} valid punches from {len(all_logs)} raw log lines.")

        # 6. CREATE OR UPDATE ODOO ATTENDANCE RECORDS
        self._create_or_update_attendance(parsed_punches)

        _logger.info("--- eSSL Attendance Synchronization finished ---")

