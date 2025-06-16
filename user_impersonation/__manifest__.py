{
    'name': 'User Impersonation - Login As Any User',
    'version': '1.0',
    'category': 'Extra Tools',
    'summary': 'Admin can log in as any user',
    'description': 'The "Login As Any User" module allows administrators to '
                   'switch to any user account without the need for '
                   'passwords or other authentication.',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'wizards/user_selection_views.xml'
    ],
    'assets': {
        'web.assets_backend': [
            'user_impersonation/static/src/js/systray_button.js',
            'user_impersonation/static/src/xml/systray_button_templates.xml',
        ]},
    'images': [
        'static/description/banner.png'
    ],
    'license': 'LGPL-3',
    'installable': True,
    'auto-install': False,
    'application': False,
}