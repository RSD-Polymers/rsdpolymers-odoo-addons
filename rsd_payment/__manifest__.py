{
    'name': 'RSD Payment',
    'version': '18.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Independent internal payment workflow for approved expense reports',
    'description': '''
RSD Payment Workflow

Adds an independent internal Accounts -> Finance -> RSD Payment
workflow after native Odoo Expense Report approval.

This module does not replace or modify Odoo's native accounting,
journal entry, payment, or reconciliation flow.
''',
    'author': 'RSD Polymers',
    'website': 'https://www.rsdpolymers.com/',
    'license': 'LGPL-3',
    'depends': ['hr_expense', 'account'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/expense_sheet_views.xml',
        'views/finance_approval_views.xml',
        'views/finance_send_back_views.xml',
        'views/rsd_payment_views.xml',
        'views/menus.xml',
    ],
    'installable': True,
    'application': True,
}
