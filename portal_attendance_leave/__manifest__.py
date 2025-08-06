{
    'name': 'Portal Attendance & Leaves',
    'version': '1.0',
    'summary': 'Portal Attendance & Leaves',
    'depends': ['base', 'hr_attendance', 'hr', 'web','hr_holidays','website'],
    'data': [
        'views/portal_attendance.xml',
        'views/website_template.xml',
    ],

    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
