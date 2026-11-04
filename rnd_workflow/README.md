# R&D Project & Experiment Workflow — Odoo 18

## Version
18.0.2.1.1

## New intake architecture
Sales & Marketing no longer creates R&D Projects directly. The department creates an R&D Requirement using the structured form. R&D Manager reviews the requirement, enters the committed completion date, assigns the R&D owner, accepts it and creates the R&D Project from the accepted requirement.

## Requirement lifecycle
1. Sales & Marketing User creates a draft requirement and fills the sections based on `R&D Workflow.xlsx`.
2. Sales & Marketing selects applicable Product Physical Specification parameters from the SOP Parameter Master.
3. Sales & Marketing attaches supporting documents and submits the requirement.
4. Sales & Marketing User can see their own requirements. Sales & Marketing Manager can see and manage all departmental requirements.
5. R&D Manager reviews the requirement and may start review, request more information, accept or reject it.
6. If information is requested, Sales & Marketing can update the draft clarification and resubmit.
7. To accept, R&D Manager must set the R&D committed completion date and assign an R&D owner.
8. R&D Manager creates the project from the accepted requirement. The committed completion date is copied to the project deadline and delivery date.
9. One requirement can create only one project.

## SOP Parameter Master
Menu: R&D Workflow → Configuration → SOP Parameter Master

- R&D Manager and Odoo Administrator can create, update and archive SOP parameters.
- Internal users can read active SOP parameters for selection.
- Initial configuration is loaded from `List Of SOP For Input form.xlsx`.
- The 21 SOP workbook parameters are loaded, including dropdown options for Nature and Colour.
- `Clearity` is also loaded as a supplemental visual dropdown parameter because it appears in the Product Physical Specifications section of `R&D Workflow.xlsx` but is not present in the SOP list workbook.
- Specification types: Dropdown, Numeric Range, Number and Text.
- Existing requirement lines preserve a snapshot of parameter name, SOP number, type, unit, hint and desired specification; future SOP master edits do not rewrite submitted historical requirements.
- The initial source spellings/options are retained as supplied in the workbook for review by R&D.

## Main requirement form sections
- Request No. and Date (automatic)
- Requirement / Product Name
- Purpose
- Sample Provided & Quantity
- Product Physical Specifications (dynamic SOP parameter lines)
- Product Description (Pure Polymer / Formulation)
- Product Chemical Composition
- Implied Needs
- Application Testing Needs
- Stability Criteria
- Production Experience of Similar Product
- Statutory Requirements
- Packing
- Feasibility Statement
- Sample Requirement
- R&D Committed Completion Date (R&D Manager)
- R&D Comments
- Provided By / Approved By / Received By
- Supporting Documents

## Security model
- Sales & Marketing User (`group_rnd_sm`): create and manage own draft/clarification requirements; submit own requirements; read own submissions.
- Sales & Marketing Manager (`group_rnd_sm_manager`): inherits Sales & Marketing User access; can view and manage all Sales & Marketing requirements and submit on behalf of the department.
- R&D User (`group_rnd_officer`): no read access to `rnd.project`; can read and update only experiments assigned to them; cannot create projects or experiments.
- R&D Manager (`group_rnd_owner`): full requirement review access, creates projects from accepted requirements, full project and experiment access, and SOP configuration.
- QC Officer: retains project read access and can read/update assigned QC experiments.
- Performance Officer: retains project read access and can read/update assigned Performance experiments.
- Odoo Administrator: can configure SOP parameters.

Record rules enforce assigned experiment access. Project menu and model ACL do not grant project read access to R&D Users. R&D Users see a stored project display label on their assigned experiment, not the project record itself.

## Existing R&D execution workflow
1. R&D Manager creates an experiment under a project in Execution stage.
2. R&D Manager assigns the experiment to an R&D User and selects QC/Performance users.
3. Assigned R&D User starts execution, records execution notes and submits for QC.
4. Assigned QC user accepts, starts QC analysis, records the QC report and submits it.
5. R&D Manager assigns the Performance check.
6. Assigned Performance user starts the check, records the performance report and submits it.
7. R&D Manager finalizes the experiment.
8. When every experiment is Done, R&D Manager moves the project to Final Review and closes it.

## Workflow configuration
- Odoo Administrator can configure the default R&D Project Owner and experiment-stage activity notifications under Settings → R&D Workflow.
- The configured default owner is prefilled on new R&D Requirements only when that user belongs to the R&D Manager group.
- Experiment reset retains the experiment number, project and assigned R&D/QC/Performance users, while clearing execution notes, QC report/date and Performance report/date.

## Deployment / upgrade
1. Back up the pre-production database and current custom addon folder.
2. Replace the existing `rnd_workflow` addon folder with this version.
3. Ensure the Odoo service user owns/reads the addon files.
4. Restart Odoo and update the Apps list.
5. Upgrade **R&D Project & Experiment Workflow** on pre-production.
6. Assign users to the updated groups:
   - Sales & Marketing User
   - Sales & Marketing Manager
   - R&D User
   - R&D Manager
   - QC Officer
   - Performance Officer
7. Configure the SOP Parameter Master and verify all imported options and desired specifications with R&D.
8. Test the complete workflow with separate test users before production deployment.

## Important upgrade notes
- Existing `group_rnd_sm`, `group_rnd_officer` and `group_rnd_owner` XML IDs are retained to preserve group assignments, but their display names/permissions are updated.
- Existing Sales-created records in `rnd.project` are not automatically migrated into `rnd.requirement`. Review existing records before enabling the new process.
- Existing projects remain in the database. New projects must be created from accepted requirements.
- The initial workbook contains the text `Required Range` for many parameters; this is imported as a guidance hint, not as a numeric default. Specific Gravity retains the supplied `1.15 - 1.25` default.
- Runtime installation/upgrade and browser testing must be completed on the Odoo 18 pre-production server. This workspace does not contain a running Odoo server/database.
