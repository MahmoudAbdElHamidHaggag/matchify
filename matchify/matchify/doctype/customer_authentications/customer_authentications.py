import frappe
from frappe.utils import getdate
from frappe.model.document import Document
from frappe.core.doctype.user_permission.user_permission import get_user_permissions
from frappe.utils.user import UserPermissions

class CustomerAuthentications(Document):
    pass

@frappe.whitelist()	
def get_customers_data(identify_customers, customer_group=None, customer=None, sales_person=None, date=None):
    date = getdate(date)
    customers = []

    if identify_customers == "All Customer":
        user = frappe.session.user
        perms = get_user_permissions(user)
        allowed_customers = [x["doc"] for x in perms.get("Customer", [])]
        allowed_groups = [x["doc"] for x in perms.get("Customer Group", [])]
        group_customers = frappe.get_all("Customer",filters={"customer_group": ["in", allowed_groups]},fields=["name"]) 
        group_customer_names = [c["name"] for c in group_customers]
        final_allowed_names = list(set(allowed_customers + group_customer_names))
        if not final_allowed_names:
            frappe.throw("You do not have permission to view any customer.")
        customers = frappe.get_all("Customer", filters={"name": ["in", final_allowed_names]}, fields=["name"])
        
        

    elif identify_customers == "Customer Group" and customer_group:
        customers = frappe.get_all("Customer", filters={"customer_group": customer_group})

    elif identify_customers == "Customer" and customer:
        customers = [{"name": customer}]

    elif identify_customers == "Customer by Sales Person" and sales_person:
        customers = frappe.db.sql("""
            SELECT DISTINCT parent AS name
            FROM `tabSales Team`
            WHERE parenttype = 'Customer' AND sales_person = %s
        """, (sales_person,), as_dict=True)


    result = []
    for cust in customers:
        total = frappe.db.sql("""
            SELECT SUM(debit) - SUM(credit)
            FROM `tabGL Entry`
            WHERE party_type='Customer' AND party=%s AND docstatus=1 AND is_cancelled=0 AND posting_date<=%s
        """, (cust["name"], date))[0][0] or 0

        result.append({
            "customer_id": cust["name"],
            "customer_name": frappe.db.get_value("Customer", cust["name"], "customer_name"),
            "balance": total
        })

    return result
