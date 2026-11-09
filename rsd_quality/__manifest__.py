{
    'name': 'RSD Quality Customizations',
    'icon': '/rsd_quality/static/description/icon.png',
    'version': '18.0.1.3.1',
    'category': 'Quality/Quality',
    'summary': 'Production unloading requests, Performance Testing and Internal COA',
    'description': """
        - Restricts Quality Checks (Pass/Fail) strictly to the Quality Department.
        - Provides the Production Supervisor to Production Chemist unloading request workflow.
        - Provides product-wise QC specification templates and automatic Performance Test / Internal COA evaluation.
        - Uses the QC Performance Test workflow for application/performance testing.
        - Shows only the Request Unloading action on Manufacturing Orders, restricted to Production Supervisors.
    """,
    'author': 'RSD Polymers',
    'depends': ['quality_control', 'hr', 'mrp', 'mail', 'rsd_qa_management'],
    'data': [
        'data/unloading_request_sequence.xml',
        'data/qc_stage_test_sequence.xml',
        'data/testing_sequences.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/quality_check_views.xml',
        'views/unloading_request_views.xml',
        'views/testing_views.xml',
        'views/mrp_production_unloading_views.xml',
        'views/qc_workflow_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}