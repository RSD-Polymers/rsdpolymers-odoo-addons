{
    'name': 'RSD Polymer Project Module Customization',
    'version': '1.0',
    'category': 'Project',
    'author': 'RSD Polymers',
    'depends': ['project', 'web', 'project_enterprise', 'hr_timesheet', 'timesheet_grid'],
    'data': [
        'security/ir.model.access.csv',
        'views/project_task_views.xml',
        'views/res_groups_view.xml',
        'views/project_task_reject_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'project_customization/static/src/js/project_task_state_selection_extend.js',
        ],
    },
    'icon': 'project_customization/static/description/icon.png',
    'installable': True,
    'application': False,
    'license': 'OEEL-1',
}
