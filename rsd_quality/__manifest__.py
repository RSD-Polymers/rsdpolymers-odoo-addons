{
    'name': 'RSD Quality Customizations',
    'icon': '/rsd_quality/static/description/icon.png',
    'version': '18.0.1.2.2',
    'category': 'Quality/Quality',
    'summary': 'Production unloading requests, sample testing and application testing',
    'description': """
        - Restricts Quality Checks (Pass/Fail) strictly to the Quality Department.
        - Provides the Production Supervisor to Production Chemist unloading request workflow.
        - Provides production Sample Test and Application Test workflows with QA review and deviation linkage.
    """,
    'author': 'RSD Polymers',
    'depends': ['quality_control', 'hr', 'mrp', 'mail', 'rsd_qa_management'],
    'data': [
        'data/unloading_request_sequence.xml',
        'data/testing_sequences.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/quality_check_views.xml',
        'views/unloading_request_views.xml',
        'views/testing_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}