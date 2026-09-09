{
    'name': 'RSD Polymer Tally Integration',
    'icon': '/tally_integration/static/description/icon.png',
    'version': '1.0',
    'category': 'Accounting/Accounting',
    'summary': 'Custom module to push accounting entries from Odoo to Tally ERP/Prime.',
    'description': """
        Tally Integration
        ====================
        This app allows you to integrate Odoo with Tally ERP/Prime with SOAP protocol. It uses XML
        based data push to Tally with SOAP request.
        """,
    'author': 'RSD Polymer',
    'website': 'https://www.rsdpolymers.com/',
    'depends': ['account', 'base', 'l10n_in'],
    'data': [
        'security/ir.model.access.csv',
        'data/account_tally_ledger_sequence.xml',
        'views/tally_config_views.xml',
        'views/account_move_views_inherit.xml',
        'views/account_account_views.xml',
        'views/tally_ledger_group_views.xml',
        'wizard/tally_import_wizard_views.xml',
        'views/tally_partner_staging_views.xml',
        'views/res_partner_views.xml',
        'views/product_views.xml',
        'views/account_tax_views.xml',
        'views/account_payment_view_inherit.xml',
        'views/res_company_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
