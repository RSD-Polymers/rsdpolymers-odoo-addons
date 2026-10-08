{
    'name': 'R&D Project & Experiment Workflow',
    'version': '18.0.1.1.0',
    'category': 'Manufacturing/Quality',
    'summary': 'Sales & Marketing to R&D requirement, planning, batch/experiment execution, QC and performance review workflow.',
    'description': """
R&D Project & Experiment Workflow
==================================
Implements the full pipeline:

Sales & Marketing -> R&D receives requirement -> R&D project owner reviews & accepts
-> delivery date to S&M -> R&D project planning (Proposal / BMP / RM & Equipment Planning)
-> Batch/Experiment planning -> Create experiment/batch (mandatory experiment no.)
-> Assign to R&D user -> Experiment execution -> Submit for QC -> QC user accepts
-> QC analysis -> QC report submission -> R&D project owner reviews result
-> Performance check assigned -> Performance user checks -> Performance report submitted
-> R&D project owner final review -> Project finalization -> Closed
""",
    'author': 'RSD Polymers',
    'website': '',
    'license': 'LGPL-3',
    'depends': ['base', 'mail'],
    'data': [
        'security/rnd_workflow_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/rnd_planning_type_data.xml',
        'views/rnd_project_views.xml',
        'views/rnd_experiment_views.xml',
        'views/rnd_planning_type_views.xml',
        'views/menu_views.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
