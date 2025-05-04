import frappe
from frappe.utils import getdate
from frappe.model.document import Document

class CustomerAuthentications(Document):
    pass

@frappe.whitelist()
def get_customers_data(identify_customers, customer_group=None, customer=None, sales_person=None, date=None):
    date = getdate(date)
    customers = []

    # إذا تم اختيار "كل العملاء"
    if identify_customers == "All Customer":
        customers = frappe.get_all("Customer", fields=["name"])

    # إذا تم اختيار "مجموعة العملاء"
    elif identify_customers == "Customer Group" and customer_group:
        customers = frappe.get_all("Customer", filters={"customer_group": customer_group}, fields=["name"])

    # إذا تم اختيار "عميل"
    elif identify_customers == "Customer" and customer:
        customers = [{"name": customer}]

    # إذا تم اختيار "العملاء حسب عضو المبيعات"
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
            "customer": cust["name"],
            "balance": total
        })

    return result