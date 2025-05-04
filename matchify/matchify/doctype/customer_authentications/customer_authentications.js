frappe.ui.form.on('Customer Authentications', {
    refresh: function (frm) {
        // إصلاح set_query - الحقل في الفورم الرئيسي
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

        let args = {
            identify_customers,
            date
        };

        if (identify_customers === "Customer Group") {
            args.customer_group = frm.doc.customer_group;
        } else if (identify_customers === "Customer") {
            args.customer = frm.doc.customer;
        } else if (identify_customers === "Customer by Sales Person") {
            // أضفنا السطر التالي لتأكيد القيمة المُرسلة
            console.log("Sales Person Selected:", frm.doc.customer_by_sales_person); 
            args.sales_person = frm.doc.customer_by_sales_person;  // تأكد من أن هذا هو الحقل الصحيح
        }

        frappe.call({
            method: "matchify.matchify.doctype.customer_authentications.customer_authentications.get_customers_data",
            args: args,
            callback: function (r) {
                frm.clear_table("customer_balance");
                (r.message || []).forEach(row => {
                    frm.add_child("customer_balance", {
                        customer: row.customer,
                        balance: row.balance
                    });
                });
                frm.refresh_field("customer_balance");
            }
        });
    }
});
