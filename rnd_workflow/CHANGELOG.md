# Changelog

## 18.0.2.0.0
- Added Sales & Marketing requirement submission separate from R&D project management.
- Added Sales & Marketing Manager group with department-wide requirement visibility and draft management.
- Added configurable SOP Parameter Master and seeded workbook values/options.
- Added dynamic Product Physical Specifications lines with dropdown, range, number and text input types.
- Added requirement review, information request, accept/reject and project conversion workflow.
- R&D committed completion date is copied to the project deadline; later project deadline changes synchronize back to the requirement.
- Restricted R&D Users to assigned experiments and removed their project model read access.
- Kept QC and Performance assignment-based experiment access and existing project read access.
- Preserved legacy project records with a manager-only migration action.

## 18.0.2.1.0
- Hardened SOP dropdown option validation against cross-parameter, archived and non-dropdown options.
- Made numeric entered-value flags server-derived during create/write, including explicit zero values and cleared inputs.
- Prevented direct tampering with SOP snapshot fields and moving parameter lines between requirements.
- Extended specification constraints to reject numeric inputs on incompatible specification types.

## 18.0.2.1.1 (corrective hardening)
- Removed caller-controlled context flags that bypassed workflow write restrictions in requirements, projects and experiments.
- Routed authorized workflow transitions through private internal write helpers.
- Enforced consistency between Project Deadline and Committed Completion Date when both are supplied.
- Kept the source requirement's committed date synchronized when the project deadline changes.
- Notify R&D Managers when Sales & Marketing resubmits requested information.
- Enforced Draft as the initial experiment state and generated experiment numbers server-side.
- Prevented experiment reports, dates and archive status from being supplied during creation; restricted archive changes to R&D Managers.
- Validated R&D, QC and Performance assignees against their required security groups.
- Reset experiment stage reports, notes and dates while retaining its number, project and assignments.
- Validated project owners and synchronized project-owner changes to the source requirement.
- Applied the configured default R&D owner to new requirements.
- Tightened QC and Performance experiment write rules to their respective assignments.
- Made the project experiment list read-only; create experiments through the dedicated Experiments action.
- Added the missing system settings view and clarified notification setting scope.

## 18.0.2.1.2
- Fixed SOP specification onchange flags so clearing hidden numeric inputs does not trigger false validation errors.
- Preserved valid numeric zero values and correctly cleared entered-value flags for minimum, maximum and numeric value fields.
