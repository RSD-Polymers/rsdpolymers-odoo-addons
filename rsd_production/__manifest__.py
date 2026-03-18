{
    "name": "RSD Polymer Production",
    'icon': '/rsd_sales/static/description/icon.png',
    "version": "18.0.1.0",
    "summary": "Production Module Customization",
    'description': """
        This is RSD Polymer Customization module for Sales.
        """,
    'author': 'RSD Polymer',
    'website': 'https://www.rsdpolymers.com/',
    "depends": ["stock", "sale", "account", "rsd_sales", "mrp", "product"],
    "data": [
        "data/sequence.xml",
        "security/ir.model.access.csv",
        "reports/delivery_challan_report.xml",
        "reports/delivery_challan_template.xml",
        "reports/mo_label_report.xml",
        "reports/mo_label_template.xml",
        "reports/print_label_report.xml",
        "reports/print_label_template.xml",
        "views/mrp_production_views.xml",
        "views/rm_issue_views.xml",
    ],
    "installable": True,
    'application': False,
    'license': 'LGPL-3',
}
