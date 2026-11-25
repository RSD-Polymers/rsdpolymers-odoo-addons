{
    'name': 'RSD Quality Customizations',
    'icon': '/rsd_quality/static/description/icon.png',
    'version': '18.0.1.4.5',
    'category': 'Quality/Quality',
    'summary': 'Production unloading requests, Performance Testing and Internal COA',
    'description': """
        - Restricts Quality Checks (Pass/Fail) strictly to the Quality Department.
        - Provides the Production Supervisor to Production Chemist unloading request workflow.
        - Provides product-wise QC specification templates and automatic Performance Test / Internal COA evaluation.
        - Consolidated R&D Sample Request and single-Experiment review workflow.
        - Uses the QC Performance Test workflow for application/performance testing.
        - Provides administrator-wide unloading workflow access, Production Supervisor read access at every stage, and controlled physical-modification completion with audit details.
    """,
    'author': 'RSD Polymers',
    'depends': ['quality_mrp', 'quality_control', 'hr', 'mrp', 'mail', 'rsd_qa_management','rsd_sales', 'rnd_workflow',],
    'data': [
        'data/unloading_request_sequence.xml',
        'data/application_request_sequence.xml',
        'security/application_request_security.xml',
        'data/qc_stage_test_sequence.xml',
        'data/testing_sequences.xml',
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/quality_check_views.xml',
        'views/unloading_request_views.xml',
        'views/testing_views.xml',
        'data/application_test_data.xml',
        'views/application_request_views.xml',
        'views/application_request_menu.xml',
        'views/mrp_production_unloading_views.xml',
        'views/qc_workflow_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}