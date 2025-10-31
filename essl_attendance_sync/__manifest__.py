{
    'name': "eSSL RSD Attendance Sync",
    'icon': '/essl_attendance_sync/static/description/icon.png',
    'version': '1.0',
    'summary': "Automated synchronization of eSSL Biometric Attendance Logs via SOAP API.",
    'description': """
        Connects to the eSSL WebAPIService.asmx (GetTransactionsLog) via SOAP 
        to fetch daily attendance punches and create/update hr.attendance records.
        Requires the 'zeep' Python library.
    """,
    'author': 'RSD Polymers',
    'website': 'https://www.rsdpolymers.com/',
    'category': 'Human Resources',
    'version': '18.0.1.0.0',
    'depends': ['hr_attendance', 'base_setup'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'data/ir_cron_data.xml',
        'views/employee_inherit_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}