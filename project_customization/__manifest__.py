{
    'name': 'RSD Polymer Project Module Customization',
    'icon': '/project_customization/static/description/icon.png',
    'version': '1.0',
    'category': 'Project',
    'author': 'RSD Polymers',
    'depends': ['project', 'web', 'project_enterprise', 'hr_timesheet', 'timesheet_grid'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_task_views.xml',
        'views/res_groups_view.xml',
        'views/project_task_reject_wizard_views.xml',
        'data/project_task_reject_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'project_customization/static/src/js/project_task_state_selection_extend.js',
            'project_customization/static/src/xml/project_task_state_selection_extend_custom.xml',
        ],
    },
    'installable': True,
    'application': False,
    'license': 'OEEL-1',
}
