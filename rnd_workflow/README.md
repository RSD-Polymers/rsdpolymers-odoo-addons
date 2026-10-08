# R&D Project & Experiment Workflow — Odoo 18

## Purpose
This module implements the R&D workflow from Sales & Marketing requirement intake through R&D review, project planning, batch/experiment execution, QC, performance checking, final review, and closure.

## Workflow
1. Sales & Marketing creates a New Requirement.
2. Sales & Marketing selects an R&D Project Owner and submits to R&D.
3. R&D Owner reviews the requirement and enters the delivery date.
4. R&D Owner accepts the requirement and moves it to Project Planning.
5. R&D Owner selects one or more planning types: Proposal, BMP, RM / Equipment Planning.
6. R&D Owner starts Batch / Experiment Execution.
7. R&D Officer creates an Experiment under the project.
8. R&D Owner assigns the Experiment to an R&D user and selects QC/Performance users.
9. Assigned R&D user starts execution, records execution notes, and submits for QC.
10. Assigned QC user accepts the request, starts QC analysis, records the QC report, and submits it.
11. R&D Owner assigns the Performance check.
12. Assigned Performance user starts the check, records the performance report, and submits it.
13. R&D Owner finalizes the Experiment.
14. When every Experiment is Done, R&D Owner moves the Project to Final Review.
15. R&D Owner closes the Project.

## Security model
- Sales & Marketing: create/edit own New Requirements and submit them.
- R&D Officer: read projects; create experiments; edit execution notes only on assigned experiments; perform assigned R&D execution transitions.
- QC Officer: read projects; edit QC report only on assigned QC experiments; perform QC transitions.
- Performance Officer: read projects; edit performance report only on assigned Performance experiments; perform Performance transitions.
- R&D Project Owner / Manager: full workflow control, assignments, planning, final review, close, reset, and configuration.

Workflow status changes are blocked in `write()` and must go through the approved server-side workflow methods. UI button visibility is an additional usability layer, not the security boundary.

## Deployment
1. Copy the `rnd_workflow` folder into the custom addons path.
2. Ensure the Odoo service user can read the folder.
3. Restart Odoo.
4. Update the Apps list.
5. Install **R&D Project & Experiment Workflow** on pre-production first.
6. Configure the R&D Project Owner / Manager group and assign users to the appropriate groups.
7. Open R&D Workflow → Configuration → Settings and set the default R&D owner and activity notification setting.
8. Test the complete workflow with separate test users for Sales, R&D, QC and Performance.
9. Test unauthorized actions: each role must receive a UserError and must not be able to change the workflow through direct editing/import/API.
10. After successful pre-production validation, deploy the same module version to production and upgrade the module.

## Important behavior
- Experiments can only be created after a project enters Batch / Experiment Execution.
- A project cannot move to Final Review until at least one Experiment exists and every Experiment is Done.
- A closed project cannot be reset.
- A Done experiment cannot be reset; create a new experiment for a rerun to preserve audit history.
- Only Draft experiments and New Requirement projects can be deleted.
- Stage-change activities respect the `Notify users on stage change` setting.

## Validation performed before release
- Python AST syntax validation: passed.
- XML parsing validation: passed for all XML files.
- Access CSV structure validation: passed for 12 access rows.
- Odoo runtime installation/upgrade test: not available in this workspace and must be executed on the Odoo 18 pre-production server.
