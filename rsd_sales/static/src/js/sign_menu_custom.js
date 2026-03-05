/** @odoo-module **/

import { registry } from "@web/core/registry";
import { user } from "@web/core/user";

// Access Odoo's global Cog Menu registry
const cogMenuRegistry = registry.category("cogMenu");

// Fetch the "Request Signature" item directly by its registry key
const signRequestItem = cogMenuRegistry.get("sign-request-menu", null);

if (signRequestItem) {
    const originalIsDisplayed = signRequestItem.isDisplayed;

    // Override the display logic
    signRequestItem.isDisplayed = async (env) => {
        // 1. Run the core Odoo checks first (is it a form view? is sign installed?)
        const isOriginallyDisplayed = await originalIsDisplayed(env);
        if (!isOriginallyDisplayed) {
            return false;
        }

        // 2. Always allow the System Administrator
        if (user.isAdmin) {
            return true;
        }

        // 3. Check specific access groups
        // Note: user.hasGroup() is asynchronous in Odoo 18, so we await the results
        const isSystem = await user.hasGroup("base.group_system");
        const isSaleManager = await user.hasGroup("sales_team.group_sale_manager");
        const isSaleLeads = await user.hasGroup("sales_team.group_sale_salesman_all_leads");
        const isSalesman = await user.hasGroup("sales_team.group_sale_salesman");
        const isCustomExport = await user.hasGroup("__export__.res_groups_222_4190eb7c");

        // 4. Return true if they have ANY of the above groups
        return isSystem || isSaleManager || isSaleLeads || isSalesman || isCustomExport;
    };
}