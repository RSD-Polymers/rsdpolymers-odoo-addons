{
    'name': 'RSD Quality Customizations',
    'icon': '/rsd_quality/static/description/icon.png',
    'version': '18.0.1.0.0',
    'category': 'Quality/Quality',
    'summary': 'Custom logic and security for RSD Quality Checks',
    'description': """
        - Restricts Quality Checks (Pass/Fail) strictly to the Quality Department.
    """,
    'author': 'RSD Polymers',
    'depends': ['quality_control', 'hr'],
    'data': [
        'views/quality_check_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}