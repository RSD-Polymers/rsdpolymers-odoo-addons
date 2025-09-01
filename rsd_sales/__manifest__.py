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
    'depends': ['base', 'sale', 'sale_management', 'mrp'],
    'data': [
        #'views/sale_order_production_menu.xml',
        'views/sale_order_views.xml',
        'views/mrp_production_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
