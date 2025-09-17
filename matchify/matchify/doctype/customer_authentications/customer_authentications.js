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

        frm.set_query("customer_by_sales_person", () => ({ filters: { enabled: 1 } }));

        // ====== Action dropdown يظهر فقط بعد الحفظ ======
        frm.page.clear_custom_actions && frm.page.clear_custom_actions();
        frm.custom_actions_added = false;

        if (!frm.is_new() && frm.doc.name && frm.doc.docstatus !== 2) {
            add_actions(frm);
        }
    },

    identify_customers(frm) { frm.trigger("fetch_customer_data"); },
    customer_group(frm) { frm.trigger("fetch_customer_data"); },
    customer(frm) { frm.trigger("fetch_customer_data"); },
    customer_by_sales_person(frm) { frm.trigger("fetch_customer_data"); },
    date(frm) { frm.trigger("fetch_customer_data"); },

    // شيك بوكسات الرصيد
    show_debit_balance(frm)  { frm.trigger("fetch_customer_data"); },
    show_zero_balance(frm)   { frm.trigger("fetch_customer_data"); },
    show_credit_balance(frm) { frm.trigger("fetch_customer_data"); },

    // شيك بوكس: إظهار العملاء التي لها إيميل فقط
    show_only_with_email(frm) { frm.trigger("fetch_customer_data"); },

    fetch_customer_data: function (frm) {
        const identify_customers = frm.doc.identify_customers;
        const date = frm.doc.date;
        if (!identify_customers || !date) return;
        if (identify_customers === "Customer Group" && !frm.doc.customer_group) return;
        if (identify_customers === "Customer" && !frm.doc.customer) return;
        if (identify_customers === "Customer by Sales Person" && !frm.doc.customer_by_sales_person) return;

        // تحقّق بسيط لصيغة الإيميل
        function hasEmail(val) {
            if (!val) return false;
            const s = String(val).trim();
            if (!s) return false;
            const at = s.indexOf('@');
            if (at <= 0) return false;
            const local = s.slice(0, at);
            const domain = s.slice(at + 1);
            if (!local || !domain || !domain.includes('.')) return false;
            return true;
        }

        const show_debit  = cint(frm.doc.show_debit_balance)  === 1;
        const show_zero   = cint(frm.doc.show_zero_balance)   === 1;
        const show_credit = cint(frm.doc.show_credit_balance) === 1;
        const show_email_only = cint(frm.doc.show_only_with_email) === 1;

        const none_checked_balance = !show_debit && !show_zero && !show_credit;

        let args = {
            identify_customers,
            date,
            show_debit_balance: show_debit ? 1 : 0,
            show_zero_balance: show_zero ? 1 : 0,
            show_credit_balance: show_credit ? 1 : 0
        };

        if (identify_customers === "Customer Group") {
            args.customer_group = frm.doc.customer_group;
        } else if (identify_customers === "Customer") {
            args.customer = frm.doc.customer;
        } else if (identify_customers === "Customer by Sales Person") {
            args.sales_person = frm.doc.customer_by_sales_person;
        }

        const show_loading = identify_customers !== "Customer";
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
                    </div>`,
                title: 'Loading',
                indicator: 'blue',
                wide: true
            });

            setTimeout(() => {
                let percent = 0;
                interval = setInterval(() => {
                    if (percent < 90) {
                        percent += 10;
                        $('#custom-progress-bar').css('width', percent + '%').text(percent + '%');
                    }
                }, 50);
            }, 100);
        }

        frappe.call({
            method: "matchify.matchify.doctype.customer_authentications.customer_authentications.get_customers_data",
            args,
            callback: function (r) {
                if (interval) clearInterval(interval);
                frm.clear_table("customer_balance");

                const rows = (r.message || []);
                rows.forEach(row => {
                    const bal = flt(row.balance || 0);
                    const is_debit  = bal >  0.0000001;
                    const is_zero   = Math.abs(bal) <= 0.0000001;
                    const is_credit = bal < -0.0000001;

                    const pass_balance = none_checked_balance
                        ? true
                        : ((is_debit  && show_debit) ||
                           (is_zero   && show_zero)  ||
                           (is_credit && show_credit));
                    if (!pass_balance) return;

                    let email_val = (row.email || "").trim();
                    const ok_email = hasEmail(email_val);
                    if (show_email_only && !ok_email) return;
                    if (!ok_email) email_val = "";

                    frm.add_child("customer_balance", {
                        customer: row.customer_id,
                        customer_name: row.customer_name,
                        email: email_val,
                        balance: flt(row.balance || 0),
                        status_send: "",
                        visible_in_batch: ok_email ? 1 : 0,
                        delivery_message: ok_email ? "" : "No email found"
                    });
                });

                frm.refresh_field("customer_balance");

                if (show_loading) {
                    $('#custom-progress-bar').css('width', '100%').text('100%');
                    setTimeout(() => {
                        frappe.hide_msgprint();
                        frm.refresh_field("customer_balance");
                    }, 300);
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

// ======================
// Actions
// ======================

function add_actions(frm) {
    if (frm.custom_actions_added) return;
    frm.add_custom_button(__('Send to email'), () => open_send_dialog(frm), __('Action'));
    frm.add_custom_button(__('Export Zip File'), () => export_zip(frm), __('Action'));
    frm.add_custom_button(__('Export Excel File'), () => export_excel(frm), __('Action'));
    frm.add_custom_button(__('Export CSV File'), () => export_csv(frm), __('Action'));
    frm.custom_actions_added = true;
}

// يضمن: محفوظ + لا تغييرات + Submitted (يعرض تأكيد للـ Submit لو لزم)
async function ensure_finalized(frm) {
    if (frm.is_new() || !frm.doc.name) {
        frappe.msgprint(__('احفظ المستند أولًا'));
        return false;
    }
    if (frm.is_dirty()) {
        await frm.save(); // نحفظ التعديلات
    }
    if (frm.doc.docstatus !== 1) {
        const yes = await new Promise((res) => {
            frappe.confirm(__('يلزم Submit قبل المتابعة. تنفيذ الآن؟'), () => res(true), () => res(false));
        });
        if (!yes) return false;
        await frm.savesubmit();
        await frm.reload_doc();
    }
    return true;
}

// وجود صفوف ظاهرة تصلح للتعامل
function get_visible_rows(frm) {
    return (frm.doc.customer_balance || []).filter(r => cint(r.visible_in_batch) === 1);
}

function after_action_lock(frm) {
    // قفل الواجهة بعد الإرسال/التصدير لمنع أي تعديل لاحق
    frm.set_read_only();
    frm.disable_save();
}

function open_send_dialog(frm) {
    ensure_finalized(frm).then(ok => {
        if (!ok) return;

        const rows = get_visible_rows(frm);
        if (!rows.length) {
            frappe.msgprint(__('لا توجد صفوف ظاهرة للإرسال.'));
            return;
        }

        const d = new frappe.ui.Dialog({
            title: __('Send to email'),
            fields: [
                { label: __('From Email'), fieldname: 'from_email', fieldtype: 'Link', options: 'Email Account', reqd: 1 },
                { label: __('Email Template'), fieldname: 'email_template', fieldtype: 'Link', options: 'Email Template' }
            ],
            primary_action_label: __('Send'),
            primary_action(values) {
                d.hide();
                frappe.call({
                    method: "matchify.matchify.doctype.customer_authentications.customer_authentications.send_customer_pages_via_email",
                    args: {
                        docname: frm.doc.name,
                        from_email: values.from_email || null,
                        email_template: values.email_template || null,
                        current_modified: frm.doc.modified   // قفل تفاؤلي (اختياري على السيرفر)
                    },
                    freeze: true,
                    freeze_message: __('Sending emails...'),
                    callback: function (r) {
                        const cnt = (r && r.message && r.message.sent_count) || 0;
                        if (cnt > 0) {
                            frappe.msgprint(__(`تم إرسال ${cnt} رسالة.`));
                            after_action_lock(frm);
                        } else {
                            frappe.msgprint(__('لم يتم إرسال أي رسائل. تحقق من الإيميلات/الإعدادات.'));
                        }
                    },
                    error: function (xhr) {
                        frappe.msgprint(__('تعذر الإرسال. راجع سجلات الخطأ.'));
                        console.error('send_customer_pages_via_email error:', xhr);
                    }
                });
            }
        });
        d.show();
    });
}

function export_zip(frm) {
    ensure_finalized(frm).then(ok => {
        if (!ok) return;

        const rows = get_visible_rows(frm);
        if (!rows.length) { frappe.msgprint(__('لا توجد صفوف ظاهرة للتصدير.')); return; }

        frappe.call({
            method: "matchify.matchify.doctype.customer_authentications.customer_authentications.export_customer_pages_zip",
            args: { docname: frm.doc.name, current_modified: frm.doc.modified },
            freeze: true,
            freeze_message: __('Preparing ZIP...'),
            callback: function (r) {
                if (r && r.message && r.message.file_url) {
                    window.open(r.message.file_url);
                    after_action_lock(frm);
                } else {
                    frappe.msgprint(__('No file generated.'));
                }
            },
            error: function (xhr) {
                frappe.msgprint(__('تعذر إنشاء الملف المضغوط.'));
                console.error('export_customer_pages_zip error:', xhr);
            }
        });
    });
}

function export_excel(frm) {
    ensure_finalized(frm).then(ok => {
        if (!ok) return;

        const rows = get_visible_rows(frm);
        if (!rows.length) { frappe.msgprint(__('لا توجد صفوف ظاهرة للتصدير.')); return; }

        frappe.call({
            method: "matchify.matchify.doctype.customer_authentications.customer_authentications.export_customer_rows_excel",
            args: { docname: frm.doc.name, current_modified: frm.doc.modified },
            freeze: true,
            freeze_message: __('Preparing Excel...'),
            callback: function (r) {
                if (r && r.message && r.message.file_url) {
                    window.open(r.message.file_url);
                    after_action_lock(frm);
                } else {
                    frappe.msgprint(__('No file generated.'));
                }
            },
            error: function (xhr) {
                frappe.msgprint(__('تعذر إنشاء ملف الإكسيل.'));
                console.error('export_customer_rows_excel error:', xhr);
            }
        });
    });
}

function export_csv(frm) {
    ensure_finalized(frm).then(ok => {
        if (!ok) return;

        const rows = get_visible_rows(frm);
        if (!rows.length) { frappe.msgprint(__('لا توجد صفوف ظاهرة للتصدير.')); return; }

        frappe.call({
            method: "matchify.matchify.doctype.customer_authentications.customer_authentications.export_customer_rows_csv",
            args: { docname: frm.doc.name, current_modified: frm.doc.modified },
            freeze: true,
            freeze_message: __('Preparing CSV...'),
            callback: function (r) {
                if (r && r.message && r.message.file_url) {
                    window.open(r.message.file_url);
                    after_action_lock(frm);
                } else {
                    frappe.msgprint(__('No file generated.'));
                }
            },
            error: function (xhr) {
                frappe.msgprint(__('تعذر إنشاء ملف CSV.'));
                console.error('export_customer_rows_csv error:', xhr);
            }
        });
    });
}
