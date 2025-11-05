import logging

from odoo import fields, http, _
from odoo.http import request
from datetime import datetime, date, timedelta
from odoo.addons.auth_totp.controllers.home import Home
from werkzeug.utils import redirect
import calendar
import base64
import random


class PortalAttendanceLeaves(http.Controller):

    def _get_employee(self):
        return request.env['hr.employee'].sudo().search([('user_id', '=', request.uid)], limit=1)

    def _get_last_attendance(self, employee):
        return request.env['hr.attendance'].sudo().search(
            [('employee_id', '=', employee.id)],
            order='check_in desc',
            limit=1
        )

    @http.route('/checkin/do', type='http', auth='public', website=True, methods=['POST'])
    def portal_checkin_do(self, **post):
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my')

        last_attendance = self._get_last_attendance(employee)
        if last_attendance and not last_attendance.check_out:
            return request.redirect('/my/attendance')  # Already checked in

        request.env['hr.attendance'].sudo().create({
            'employee_id': employee.id,
            'check_in': fields.Datetime.now(),
        })
        return request.redirect('/my/attendance')

    @http.route('/checkout/do', type='http', auth='user', website=True, methods=['POST'])
    def portal_checkout_do(self, **post):
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my')

        last_attendance = self._get_last_attendance(employee)
        if last_attendance and not last_attendance.check_out:
            last_attendance.sudo().write({'check_out': fields.Datetime.now()})
        return request.redirect('/my/attendance')

    @http.route(['/my/attendance'], type='http', auth='user', website=True)
    def portal_attendance(self, **kw):
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.uid)], limit=1)
        attendances = request.env['hr.attendance'].sudo().search([('employee_id', '=', employee.id)],
                                                                 order='check_in desc')
        worked_hours = 0.0
        for att in attendances:
            if att.check_in and att.check_out if att.check_out else fields.Datetime.now():
                delta = att.check_out if att.check_out else fields.Datetime.now() - att.check_in
                print(delta)
                if att.check_out and att.check_in:
                    worked_hours = round(delta.second / 3600, 2)
                else:
                    worked_hours = str(delta)
                print(worked_hours)
                break

        return request.render('portal_attendance_leave.checkin_screen_template', {
            'attendances': attendances,
            'worked_hours': worked_hours,
            'user': employee,
        })

    @http.route(['/my/timeoff'], type='http', auth='user', website=True)
    def portal_leaves(self, **kw):
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.uid)], limit=1)
        leaves = request.env['hr.leave'].sudo().search([('employee_id', '=', employee.id)],
                                                       order='request_date_from desc')
        return request.render('portal_attendance_leave.leave_list_template', {
            'leaves': leaves,
            'user': employee,
        })

    @http.route(['/my/attendance-list'], type='http', auth='user', website=True)
    def portal_my_attendance_list(self, **kw):
        # Get current user's employee
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.uid)], limit=1)
        if not employee:
            return request.redirect('/my')

        # Fetch attendance records for this employee
        attendance_records = request.env['hr.attendance'].sudo().search(
            [('employee_id', '=', employee.id)],
            order='check_in desc'
        )

        return request.render('portal_attendance_leave.attendance_list_template', {
            'records': attendance_records,
        })

    @http.route('/my/timeoff/apply', type='http', auth='user', website=True, methods=['POST'])
    def portal_leave_apply_submit(self, **post):
        employee = request.env['hr.employee'].sudo().search([('user_id', '=', request.uid)], limit=1)
        if not employee:
            return request.redirect('/my')

        leave_type_id = int(post.get('leave_type_id'))
        date_from = post.get('date_from')
        date_to = post.get('date_to')
        reason = post.get('reason', '')

        request.env['hr.leave'].sudo().create({
            'employee_id': employee.id,
            'holiday_status_id': leave_type_id,
            'request_date_from': date_from,
            'request_date_to': date_to,
            'name': reason or 'Leave Request',
            'request_unit_half': False,
        })

        return request.redirect('/my/timeoff')

    @http.route(['/my/salary-slips', '/my/salary-slips/list'], type='http', auth='user', website=True)
    def portal_salary_slips_list(self, **kw):
        """
        Show a list of the employee's payslips (salary slips).
        """
        employee = self._get_employee()
        if not employee:
            # Redirect to the main portal if no employee is found
            return request.redirect('/my')

        # Fetch confirmed or done payslips for the employee, ordered by date
        payslips = request.env['hr.payslip'].sudo().search(
            [
                ('employee_id', '=', employee.id),
                ('state', 'in', ['done', 'paid'])  # Fetch only confirmed/paid slips
            ],
            order='date_to desc'
        )

        return request.render('portal_attendance_leave.salary_slips_list_template', {
            'payslips': payslips,
            'user': employee,
            'page_name': 'salary_slips',
        })

    @http.route(['/my/salary-slips/<int:payslip_id>'], type='http', auth='user', website=True)
    def portal_salary_slip_details(self, payslip_id, **kw):
        """
        Show the details of a specific salary slip and allow PDF download.
        """
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my')

        # Fetch the specific payslip
        payslip = request.env['hr.payslip'].sudo().search([
            ('id', '=', payslip_id),
            ('employee_id', '=', employee.id)
        ], limit=1)

        if not payslip or payslip.state not in ['done', 'paid']:
            # Redirect if payslip is not found or not in a viewable state
            return request.redirect('/my/salary-slips')

        return request.render('portal_attendance_leave.salary_slip_detail_template', {
            'payslip': payslip,
            'user': employee,
            'page_name': 'salary_slips',
        })

    @http.route(['/my/salary-slips/pdf/<int:payslip_id>'], type='http', auth='user', website=True)
    def portal_salary_slip_pdf(self, payslip_id, **kw):
        """
        Generate and return the PDF for a specific salary slip.
        """
        employee = self._get_employee()
        if not employee:
            return request.redirect('/my')

        payslip = request.env['hr.payslip'].sudo().search([
            ('id', '=', payslip_id),
            ('employee_id', '=', employee.id)
        ], limit=1)

        if not payslip or payslip.state not in ['done', 'paid']:
            return request.redirect('/my/salary-slips')

        # Get the PDF report action
        report_action = request.env.ref('hr_payroll.action_report_payslip').sudo().report_action(payslip)

        # Odoo 17+ uses report_action to return the content directly
        return report_action