{
    'name': 'RSD Polymer Sales',
    'icon': '/rsd_sales/static/description/icon.png',
    'version': '1.0',
    'category': 'Sales',
    'summary': 'Sales Module Customization',
    'description': """
        This is RSD Polymer Customization module for Sales.
        """,
    'author': 'RSD Polymer',
    'website': 'https://www.rsdpolymers.com/',
    'depends': ['base', 'sale', 'sale_management', 'mrp', 'product', 'web', 'account', 'l10n_in_edi', 'sign'],
    'data': [
        'security/ir.model.access.csv',
        'views/create_mo_wizard_action.xml',
        'reports/sale_order_report.xml',
        'reports/report_custom_sales_invoice.xml',
        'views/create_mo_wizard_view.xml',
        'views/sale_order_views.xml',
        'views/mrp_production_view.xml',
        'views/product_views.xml',
        'views/account_move_inherit.xml',
        'views/product_category_views.xml',
        'views/sale_approval_wizard_views.xml',
        'views/sale_rejection_wizard_views.xml',
        'views/sale_checker_wizard.xml',
        'views/sale_checker_reject_wizard_view.xml',
        'views/stock_report_sales.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'rsd_sales/static/src/js/sign_menu_custom.js',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
