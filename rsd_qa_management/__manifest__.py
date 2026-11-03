{
    "name": "Quality Assurance",
    "version": "18.0.1.5.0",
    "category": "Quality",
    "summary": "Quality Assurance workflows including Change Control",
    "description": "Quality Assurance application with Change Control workflow, department evaluation tasks, QA review, QA Manager approval and implementation closure.",
    "author": "AP Enterprises",
    "license": "LGPL-3",
    "depends": ["base", "web", "mail", "hr"],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/qa_change_control_sequence.xml",
        "data/qa_change_control_cron.xml",
        "views/qa_change_control_views.xml",
        "views/qa_menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "rsd_qa_management/static/src/dashboard/qa_dashboard.js",
            "rsd_qa_management/static/src/dashboard/qa_dashboard.xml",
            "rsd_qa_management/static/src/dashboard/qa_dashboard.scss",
        ],
    },
    "application": True,
    "installable": True,
}
