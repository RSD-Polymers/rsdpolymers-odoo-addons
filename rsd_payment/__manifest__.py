{
    'name': 'Payment Desk',
    'icon': '/rsd_payment/static/description/icon.png',
    'version': '18.0.2.0.0',
    'category': 'Accounting',
    'summary': 'Internal payment review and payment tracking for approved expense reports',
    'description': '''
Payment Desk

Provides an independent Accounts -> Finance -> Payment workflow after native Odoo Expense Report approval.
Tracks Unpaid/Paid status without creating or modifying native Odoo payments or reconciliation records.
''',
    'author': 'RSD Polymers',
    'website': 'https://www.rsdpolymers.com/',
    'license': 'LGPL-3',
    'depends': ['hr_expense', 'account', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/finance_approval_views.xml',
        'views/finance_send_back_views.xml',
        'views/expense_sheet_views.xml',
        'views/rsd_payment_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
