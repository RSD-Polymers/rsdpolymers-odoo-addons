{
    'name': 'Portal Attendance & Leaves',
    'version': '1.0',
    'summary': 'Portal Attendance & Leaves',
    'depends': ['base', 'hr_attendance', 'hr', 'web','hr_holidays','website','hr_payroll'],
    'data': [
        'views/portal_attendance.xml',
        'views/website_template.xml',
        'views/payslip.xml',
        'views/hr_employee.xml',
    ],

    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
