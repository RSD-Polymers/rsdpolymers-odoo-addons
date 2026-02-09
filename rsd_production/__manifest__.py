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
    "depends": ["stock", "sale", "account"],
    "data": [
        "reports/delivery_challan_report.xml",
        "reports/delivery_challan_template.xml",
    ],
    "installable": True,
    'application': False,
    'license': 'LGPL-3',
}
