frappe.ui.form.on('Customer Authentications', {
    refresh: function (frm) {
        const grid = frm.get_field("customer_balance").grid;

		grid.cannot_add_rows = true;
		grid.cannot_delete_rows = true;

		setTimeout(() => {
			const wrapper = grid.wrapper;

			wrapper.find('.grid-add-row').hide();
			wrapper.find('.grid-remove-rows').hide();
			wrapper.find('.grid-row-check').hide();
			wrapper.find('.grid-check-all').hide();

			
			wrapper.find('th[data-fieldname="_check"]').hide();  
		}, 300);
		
        frm.set_query("customer_by_sales_person", () => {
            return {
                filters: {
                    enabled: 1
                }
            };
        });
    },

    identify_customers: function (frm) {
        frm.trigger("fetch_customer_data");
    },

    customer_group: function (frm) {
        frm.trigger("fetch_customer_data");
    },

    customer: function (frm) {
        frm.trigger("fetch_customer_data");
    },

    customer_by_sales_person: function (frm) {
        frm.trigger("fetch_customer_data");
    },

    date: function (frm) {
        frm.trigger("fetch_customer_data");
    },

    fetch_customer_data: function (frm) {
        const identify_customers = frm.doc.identify_customers;
        const date = frm.doc.date;

        if (!identify_customers || !date) return;
        if (identify_customers === "Customer Group" && !frm.doc.customer_group) return;
        if (identify_customers === "Customer" && !frm.doc.customer) return;
        if (identify_customers === "Customer by Sales Person" && !frm.doc.customer_by_sales_person) return;

        let args = {
            identify_customers,
            date
        };

        if (identify_customers === "Customer Group") {
            args.customer_group = frm.doc.customer_group;
        } else if (identify_customers === "Customer") {
            args.customer = frm.doc.customer;
        } else if (identify_customers === "Customer by Sales Person") {
            args.sales_person = frm.doc.customer_by_sales_person;
        }

        let show_loading = identify_customers !== "Customer";
        let dialog, interval;

        if (show_loading) {
            dialog = frappe.msgprint({
                message: `
                    <div class="text-center" style="margin-top: 10px;">
                        <p><b>Loading data...</b></p>
                        <div class="progress" style="height: 20px;">
                            <div id="custom-progress-bar" class="progress-bar progress-bar-striped progress-bar-animated bg-info"
                                role="progressbar" style="width: 0%;">0%</div>
                        </div>
                    </div>
                `,
                title: 'Loading',
                indicator: 'blue',
                wide: true
            });

            setTimeout(() => {
                let percent = 0;
                interval = setInterval(() => {
                    if (percent < 90) {
                        percent += 10;
                        $('#custom-progress-bar')
                            .css('width', percent + '%')
                            .text(percent + '%');
                    }
                }, 50);
            }, 100);
        }

        frappe.call({
            method: "matchify.matchify.doctype.customer_authentications.customer_authentications.get_customers_data",
            args: args,
            callback: function (r) {
                if (interval) clearInterval(interval);
                frm.clear_table("customer_balance");

                (r.message || []).forEach(row => {
                    frm.add_child("customer_balance", {
                        customer: row.customer_id,
                        customer_name: row.customer_name,
                        balance: row.balance
                    });
                });

                if (show_loading) {
                    $('#custom-progress-bar')
                        .css('width', '100%')
                        .text('100%');

                    setTimeout(() => {
                        frappe.hide_msgprint();
                        frm.refresh_field("customer_balance");
                    }, 300);
                } else {
                    frm.refresh_field("customer_balance");
                }
            },
            error: function () {
                if (interval) clearInterval(interval);
                if (show_loading) frappe.hide_msgprint();
                frappe.msgprint(__('An error occurred while loading data.'));
            }
        });
    }
});
