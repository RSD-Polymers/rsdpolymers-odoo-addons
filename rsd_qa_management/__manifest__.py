{
    "name": "Quality Assurance",
    "version": "18.0.1.0.0",
    "category": "Quality",
    "summary": "Quality Assurance dashboard and application menu framework",
    "description": """
Quality Assurance application scaffold for Odoo 18 Enterprise.
Includes a demo dashboard and navigation structure for future QA workflows.
    """,
    "author": "Custom Development",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "views/qa_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "qa_management/static/src/dashboard/qa_dashboard.js",
            "qa_management/static/src/dashboard/qa_dashboard.xml",
            "qa_management/static/src/dashboard/qa_dashboard.scss",
        ],
    },
    "application": True,
    "installable": True,
}
