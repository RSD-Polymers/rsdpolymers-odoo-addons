# -*- coding: utf-8 -*-
{
    'name': "RSD Polymer Purchase",
    'icon': '/rsd_purchase/static/description/icon.png',
    'summary': "Adds a flag to Purchase Orders to trigger a Work Order report layout. Creation of custom PDF reports of Purchase & Work Order",
    'description': """
        - Adds 'is_work_order' boolean field to purchase.order.
        - Overrides the standard PO report template to conditionally display
          a custom Work Order layout when the flag is checked.
    """,
    'author': 'RSD Polymer',
    'website': 'https://www.rsdpolymers.com/',
    'category': 'Purchases',
    'version': '18.0.1.0.0',
    # Ensure 'web' and 'purchase' are listed for dependencies and template inheritance
    'depends': ['base', 'web', 'purchase', 'mrp', 'stock'],
    'data': [
        'data/work_order_sequence.xml',
        'views/purchase_order_views.xml',
        'views/stock_picking_views.xml',
        # Removed the commented-out 'reports/reports.xml'
        'reports/purchase_report_templates.xml',
        'reports/grn_custom_report.xml',
    ],
    # 🚨 CRITICAL FIX: The custom CSS is registered here
    'assets': {
        'web.report_assets_common': [
            'rsd_purchase/static/src/css/po_report.css',
        ],
    },
    'license': 'LGPL-3',
}
