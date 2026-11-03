/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class QaDashboard extends Component {
    static template = "rsd_qa_management.QaDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ loading: true, error: false, data: {
            total: 0, completed: 0, pending: 0, completion_rate: 0, stages: [],
        }});
        onWillStart(async () => {
            try {
                this.state.data = await this.orm.call("qa.change.control", "get_dashboard_data", []);
            } catch (error) {
                this.state.error = true;
            } finally {
                this.state.loading = false;
            }
        });
    }

    openRequests(domain = []) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "Change Control",
            res_model: "qa.change.control",
            views: [[false, "list"], [false, "kanban"], [false, "form"]],
            domain,
        });
    }

    openPending() {
        return this.openRequests([["state", "not in", ["completed", "rejected"]]]);
    }

    openCompleted() {
        return this.openRequests([["state", "=", "completed"]]);
    }
}

registry.category("actions").add("rsd_qa_management.dashboard", QaDashboard);
