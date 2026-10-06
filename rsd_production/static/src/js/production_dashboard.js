/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class RSDProductionDashboard extends Component {
    static template = "rsd_production.ProductionDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            data: {
                total: 0,
                requested: 0,
                accepted: 0,
                in_production: 0,
                done: 0,
                cancelled: 0,
                material_ready_pending: 0,
                overdue: 0,
                products: [],
                recent: [],
            },
        });

        onWillStart(async () => {
            await this.loadDashboard();
        });
    }

    async loadDashboard() {
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "production.request",
                "get_dashboard_data",
                [],
            );
            this.state.data = data;
        } finally {
            this.state.loading = false;
        }
    }

    openRequests(kind) {
        const domains = {
            all: [],
            requested: [["state", "=", "requested"]],
            accepted: [["state", "=", "accepted"]],
            in_production: [["state", "=", "in_production"]],
            done: [["state", "=", "done"]],
            cancelled: [["state", "=", "cancelled"]],
            material_ready_pending: [["state", "=", "requested"]],
            overdue: [
                ["material_ready_date", "<", this.state.data.today],
                ["state", "not in", ["done", "cancelled"]],
            ],
        };

        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "Production Requests",
            res_model: "production.request.line",
            view_mode: "list",
            views: [[false, "list"]],
            domain: domains[kind] || [],
            target: "current",
        });
    }

    openProduct(productId) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "Production Requests",
            res_model: "production.request.line",
            view_mode: "list",
            views: [[false, "list"]],
            domain: [["product_id", "=", productId]],
            target: "current",
        });
    }

    openRequest(requestId) {
        return this.action.doAction({
            type: "ir.actions.act_window",
            name: "Production Request",
            res_model: "production.request",
            views: [[false, "form"]],
            res_id: requestId,
            target: "current",
        });
    }

    async refresh() {
        await this.loadDashboard();
    }
}

registry.category("actions").add("rsd_production_dashboard", RSDProductionDashboard);
