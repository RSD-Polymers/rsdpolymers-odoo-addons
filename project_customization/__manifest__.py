{
    'name': 'RSD Polymer Project',
    'icon': '/project_customization/static/description/icon.png',
    'version': '1.0',
    'category': 'Project',
    'author': 'RSD Polymers',
    'website': 'https://www.rsdpolymers.com/',
    'depends': ['project', 'web', 'project_enterprise', 'hr_timesheet', 'timesheet_grid', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'security/project_rules.xml',
        'security/project_task_rules.xml',
        'views/project_task_views.xml',
        'views/res_groups_view.xml',
        'views/project_task_reject_wizard_views.xml',
        'data/project_task_reject_cron.xml',
        'views/project_task_views_modification.xml',
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
