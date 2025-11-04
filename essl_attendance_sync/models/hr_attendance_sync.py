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
    def sync_essl_attendance_logs(self):
        """
        The main method executed by the Scheduled Action (Cron Job).
        Fetches attendance logs from eSSL cloud API and creates Odoo hr.attendance records.
        """
        if not Client:
            raise UserError(_("The 'zeep' library is required but not installed on the Odoo server."))

        _logger.info("--- Starting eSSL Attendance Synchronization ---")

        # 1. READ CONFIGURATIONS
        config_param = self.env['ir.config_parameter'].sudo()
        wsdl_url = config_param.get_param('essl_attendance_sync.wsdl_url')
        username = config_param.get_param('essl_attendance_sync.username')
        password = config_param.get_param('essl_attendance_sync.password')
        serial_number = config_param.get_param('essl_attendance_sync.serial_number')

        if not all([wsdl_url, username, password, serial_number]):
            _logger.error("eSSL synchronization failed: Configuration parameters missing in Settings.")
            return

        # 2. CALCULATE DATE RANGE (Last N FULL DAYS, Converted to IST for API)

        # Get the current time using standard Python library
        server_now_utc = datetime.now()
        days_to_sync = 3

        # Calculate the end/start of the range in UTC
        to_datetime_utc = server_now_utc + timedelta(days=1)
        to_datetime_utc = to_datetime_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        from_datetime_utc = to_datetime_utc - timedelta(days=days_to_sync)

        # Convert the UTC date range to IST before formatting the string for the API call
        if pytz:
            ist_tz = pytz.timezone('Asia/Kolkata')

            # Localize the naive UTC datetimes and convert them to IST datetimes
            from_dt_ist = pytz.utc.localize(from_datetime_utc, is_dst=None).astimezone(ist_tz)
            to_dt_ist = pytz.utc.localize(to_datetime_utc, is_dst=None).astimezone(ist_tz)

            # Format the IST date strings to send to the API
            from_dt_str = from_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")
            to_dt_str = to_dt_ist.strftime("%Y-%m-%dT%H:%M:%S")
        else:
            # Fallback to UTC if pytz is missing
            from_dt_str = from_datetime_utc.strftime("%Y-%m-%dT%H:%M:%S")
            to_dt_str = to_datetime_utc.strftime("%Y-%m-%dT%H:%M:%S")

        _logger.info(f"Syncing logs from {from_dt_str} to {to_dt_str} (Last {days_to_sync} full days)")

        try:
            # 3. CALL THE ESSL SOAP API
            client = Client(wsdl_url)

            # The API call payload
            response = client.service.GetTransactionsLog(
                FromDateTime=from_dt_str,
                ToDateTime=to_dt_str,
                SerialNumber=serial_number,
                UserName=username,
                UserPassword=password,
                strDataList=''
            )

            # --- FIX: Drill down to the strDataList as identified by the user ---

            # 1. Access the main result wrapper
            # --- CRITICAL FIX: Handle both Zeep object & dict responses properly ---
            if isinstance(response, dict):
                response_data = response.get('GetTransactionsLogResult')
                log_data_list = response.get('strDataList')
            else:
                response_data = getattr(response, 'GetTransactionsLogResult', None)
                log_data_list = getattr(response, 'strDataList', None)

            log_count = 0
            str_message = "Unknown"

            # Handle case where GetTransactionsLogResult gives only the log count
            if isinstance(response_data, str) and 'Logs Count:' in response_data:
                try:
                    log_count = int(response_data.split(':')[1].strip())
                    str_message = response_data
                except Exception:
                    _logger.warning(f"Could not parse log count from response: {response_data}")

            # Handle missing data list
            if not log_data_list:
                _logger.warning(
                    f"eSSL API reported {log_count} logs but strDataList missing. Response = {response}"
                )
                return

            if not log_data_list or log_count == 0:
                _logger.info(
                    f"eSSL API returned no attendance logs for the period. Message: {str_message}. Count: {log_count}")
                return

            # Handle the unauthorized/error response if it was a single log line
            if log_data_list == 'Unathorised User':
                _logger.error(f"eSSL API returned an error: {log_data_list}. Check Username/Password in Odoo Settings.")
                return

        except Fault as e:
            _logger.error(f"SOAP Fault while calling GetTransactionsLog: {e}")
            return
        except Exception as e:
            _logger.error(f"General error during SOAP call: {e}")
            return

        # 4. PARSE THE ATTENDANCE LOG DATA

        _logger.info(
            f"Received {len(log_data_list)} characters of raw log data containing {log_count} punches. Starting parsing...")

        # Logs are separated by '^'
        logs = log_data_list.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        logs = [line.strip() for line in logs if line.strip()]

        _logger.info(
            f"Received {len(log_data_list)} chars of raw log data. Log parser found {len(logs)} individual punch lines to process...")

        parsed_punches = []
        employee_obj = self.env['hr.employee']
        processed_logs_count = 0

        for log_line in logs:
            if not log_line:
                continue

            try:
                # Splitting fields based on format: DeviceID|EmployeeID|Timestamp|Status (0/1)
                fields_data = log_line.strip().split('\t')

                # We expect exactly 4 fields for this specific eSSL format
                if len(fields_data) < 2:
                    _logger.warning(f"Skipping malformed log (field count < 2): {log_line}")
                    continue

                employee_device_id = fields_data[0]
                punch_time_str = fields_data[1].strip()
                punch_status = '0'
                # Parse the raw timestamp (It is in IST/Local Time)
                punch_datetime = datetime.strptime(punch_time_str, "%Y-%m-%d %H:%M:%S")

                # --- TIMEZONE CONVERSION: Convert Local (IST) Punch Time to UTC for Odoo ---
                punch_time_utc = punch_datetime  # Default fallback

                if pytz:
                    ist = pytz.timezone('Asia/Kolkata')
                    # Localize the naive datetime object (assuming it is IST)
                    local_punch_datetime = ist.localize(punch_datetime, is_dst=None)
                    # Convert it to UTC
                    punch_time_utc = local_punch_datetime.astimezone(pytz.utc).replace(tzinfo=None)

                # Check for employee mapping (using the custom essl_device_id field)
                employee = employee_obj.search([
                    ('essl_device_id', '=', employee_device_id)
                ], limit=1)

                if not employee:
                    _logger.warning(
                        f"No Odoo Employee found for Device ID: {employee_device_id}. Skipping punch at {punch_time_str}."
                    )
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

        _logger.info(f"Successfully parsed {processed_logs_count} valid punches from {len(logs)} raw log lines.")

        # 5. CREATE OR UPDATE ODOO ATTENDANCE RECORDS
        self._create_or_update_attendance(parsed_punches)

        _logger.info("--- eSSL Attendance Synchronization finished ---")