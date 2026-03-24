{
    'name': 'RSD Inventory Customizations',
    'icon': '/rsd_inventory/static/description/icon.png',
    'version': '18.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Custom logic and security for RSD warehouse operations',
    'description': """
        - Hides validation and confirmation buttons on Delivery/Receipts for Purchase Department users.
    """,
    'author': 'RSD Polymers',
    'depends': ['stock', 'hr'],
    'data': [
        'views/stock_picking_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}