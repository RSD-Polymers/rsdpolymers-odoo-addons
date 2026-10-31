# Quality Assurance - Odoo 18

## Included
- Quality Assurance application root menu and app icon.
- Demo QA dashboard.
- Main menu and submenu placeholders:
  1. Change Management
     - Change Control
     - Document Change Request
  2. Complaints / Non-Compliance
     - Customer Complaints
     - Product Non-Conformity (OOS)
     - Process Non-Conformity (For all Dept.)
  3. Audits
     - Internal Audits
     - MRM and MOM
     - Trend Analysis
  4. Document Control (Revalidation)
     - SOP
     - Forms and Formats
     - QSM
  5. KPA/KRA

## Install
1. Copy the `qa_management` folder into an Odoo 18 custom addons directory.
2. Ensure the directory is listed in `addons_path`.
3. Restart Odoo.
4. Update Apps List and install or upgrade **Quality Assurance**.

## Current scope
This is an application shell only. Dashboard figures are static demo values.
Menus are placeholders and do not open business records.
No registration menus, forms, database models, approval workflows, business logic,
or custom security groups are included.


## Navigation and dashboard alignment
The application uses standard Odoo menu navigation: top-level QA sections appear
in Odoo's normal horizontal app navigation, with their child menus in dropdowns.
No custom left-side navigation panel is implemented.

The dashboard's sample KPI labels, workspace cards and activity examples are aligned
with the confirmed five-section QA menu structure. All displayed figures and activity
entries remain static demonstration content.
