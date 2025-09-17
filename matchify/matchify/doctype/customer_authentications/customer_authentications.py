# -*- coding: utf-8 -*-
import io
import csv
import zipfile
import random
import string

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, now_datetime
from frappe.utils.file_manager import save_file

PDF_TITLE = "Customer Page"
PREFERRED_PRINT_FORMAT = "Customer Balance PDF Pages"  # اسم تنسيق الطباعة الثابت عندك


class CustomerAuthentications(Document):
    pass


# =========================
# Helpers
# =========================

def _generate_random_token(length=10):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))


def _get_primary_contact_for_customer(customer_name: str):
    if not customer_name:
        return None

    primary = frappe.db.get_value("Customer", customer_name, "customer_primary_contact")
    if primary:
        return primary

    row = frappe.db.sql(
        """
        SELECT dl.parent
        FROM `tabDynamic Link` dl
        WHERE dl.link_doctype='Customer'
          AND dl.link_name=%s
          AND dl.parenttype='Contact'
        ORDER BY dl.parent ASC
        LIMIT 1
        """,
        (customer_name,),
        as_dict=True,
    )
    return row[0]["parent"] if row else None


def _get_primary_email_for_customer(customer_name: str) -> str:
    contact = _get_primary_contact_for_customer(customer_name)
    if not contact:
        return ""

    email = frappe.db.get_value("Contact", contact, "email_id")
    if email:
        return email

    row = frappe.db.sql(
        """
        SELECT ce.email_id
        FROM `tabContact Email` ce
        WHERE ce.parent=%s
          AND ce.email_id IS NOT NULL
          AND ce.email_id!=''
        ORDER BY ce.is_primary DESC, ce.idx ASC
        LIMIT 1
        """,
        (contact,),
        as_dict=True,
    )
    return row[0]["email_id"] if row else ""


def _norm_identify(val: str) -> str:
    if not val:
        return ""
    v = str(val).strip().lower()
    if v in {"all", "all customer", "all customers"}:
        return "all"
    if v in {"customer group", "by group"}:
        return "by_group"
    if v in {"customer", "by customer"}:
        return "by_customer"
    if v in {"customer by sales person", "by sales person", "by salesperson", "sales person"}:
        return "by_sales_person"
    return v


# =========================
# Data fetching
# =========================

@frappe.whitelist()
def get_customers_data(
    identify_customers,
    customer_group=None,
    customer=None,
    sales_person=None,
    date=None,
    show_debit_balance=None,
    show_zero_balance=None,
    show_credit_balance=None,
):
    """
    Returns list of dicts: [{customer_id, customer_name, balance, email}]
    """
    date = getdate(date) if date else getdate(now_datetime())
    mode = _norm_identify(identify_customers)

    if mode == "all":
        customers = frappe.get_all("Customer", filters={"disabled": 0}, fields=["name"])
    elif mode == "by_group" and customer_group:
        customers = frappe.get_all(
            "Customer", filters={"customer_group": customer_group, "disabled": 0}, fields=["name"]
        )
    elif mode == "by_customer" and customer:
        customers = [{"name": customer}]
    elif mode == "by_sales_person" and sales_person:
        customers = frappe.get_all(
            "Customer", filters={"lead_owner": sales_person, "disabled": 0}, fields=["name"]
        )
    else:
        customers = []

    def _bucket(bal: float) -> str:
        if bal > 0:
            return "debit"
        if bal < 0:
            return "credit"
        return "zero"

    def _flag_to_bool(val):
        if val is None:
            return None
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off"}:
            return False
        return None

    f_debit = _flag_to_bool(show_debit_balance)
    f_zero = _flag_to_bool(show_zero_balance)
    f_credit = _flag_to_bool(show_credit_balance)
    apply_balance_filter = any(v is True for v in (f_debit, f_zero, f_credit)) or any(
        v is False for v in (f_debit, f_zero, f_credit)
    )

    result = []
    for cust in customers:
        cust_name = cust.get("name") if isinstance(cust, dict) else cust

        total = frappe.db.sql(
            """
            SELECT COALESCE(SUM(debit) - SUM(credit), 0)
            FROM `tabGL Entry`
            WHERE party_type='Customer'
              AND party=%s
              AND docstatus=1
              AND is_cancelled=0
              AND posting_date<=%s
            """,
            (cust_name, date),
        )
        total_val = float(total[0][0]) if total and total[0] else 0.0

        if apply_balance_filter:
            b = _bucket(total_val)
            ok = (
                (b == "debit" and (f_debit is True))
                or (b == "zero" and (f_zero is True))
                or (b == "credit" and (f_credit is True))
            )
            if not ok:
                continue

        # جِب الإيميل من Customer ثم من الـ Contact لو فاضي
        email = frappe.db.get_value("Customer", cust_name, "email_id") or _get_primary_email_for_customer(cust_name)

        result.append(
            {
                "customer_id": cust_name,
                "customer_name": frappe.db.get_value("Customer", cust_name, "customer_name") or cust_name,
                "balance": total_val,
                "email": email,
            }
        )

    return result


# =========================
# Original bulk email (left intact)
# =========================

@frappe.whitelist()
def send_customer_auth_emails(customer_list=None, subject=None, message_template=None, use_token_link=True, from_email=None):
    import json

    if not customer_list:
        frappe.throw(_("No customers provided"))

    if isinstance(customer_list, str):
        try:
            customers = json.loads(customer_list)
        except Exception:
            customers = [c.strip() for c in customer_list.split(",") if c.strip()]
    else:
        customers = customer_list

    sent = []
    for cust in customers:
        cust_name = cust if isinstance(cust, str) else cust.get("customer_id") or cust.get("name")
        email = frappe.db.get_value("Customer", cust_name, "email_id")
        if not email:
            frappe.log_error(message=f"No email for customer {cust_name}", title="Send Auth Emails")
            continue

        token = _generate_random_token(12)
        try:
            doc = frappe.get_doc(
                {"doctype": "Customer Authentications", "customer": cust_name, "email": email, "sent_at": now_datetime()}
            )
            doc.insert(ignore_permissions=True)
        except frappe.DuplicateEntryError:
            pass
        except Exception as e:
            frappe.log_error(f"Error creating Customer Authentications for {cust_name}: {e}", "Customer Auth Insertion")

        if not subject:
            subject = _("Your authentication information")
        if not message_template:
            if use_token_link:
                link = "{site}/auth/verify?customer={customer}&token={token}".format(
                    site=frappe.utils.get_url(), customer=frappe.utils.url_quote(cust_name), token=token
                )
                body = _("Hello {customer},\n\nUse this link to authenticate: {link}\n\nToken: {token}\n\nThanks.").format(
                    customer=cust_name, link=link, token=token
                )
            else:
                body = _("Hello {customer},\n\nYour authentication token: {token}\n\nThanks.").format(
                    customer=cust_name, token=token
                )
        else:
            link = "{site}/auth/verify?customer={customer}&token={token}".format(
                site=frappe.utils.get_url(), customer=frappe.utils.url_quote(cust_name), token=token
            )
            body = message_template.replace("{{customer}}", cust_name).replace("{{token}}", token).replace("{{link}}", link)

        try:
            frappe.sendmail(
                recipients=[email],
                subject=subject,
                message=body,
                sender=from_email or None,
                expose_recipients="to",
                ignore_ssl_certificate=True,
            )
            sent.append({"customer": cust_name, "email": email})
        except Exception as e:
            frappe.log_error(f"Error sending email to {email}: {e}", "Customer Auth Email Error")

    return {"sent": sent, "count": len(sent)}


# =========================
# ACTIONS (Send/Export)
# =========================

def _render_customer_page_pdf(doc, row, wkhtml_options=None) -> tuple[str, bytes]:
    """
    يولّد PDF لصف عميل واحد باستخدام التنسيق المخصص عبر wkhtmltopdf.
    """
    import re
    from html import escape
    from frappe.utils.pdf import get_pdf
    from frappe.utils import formatdate, now_datetime, fmt_money, money_in_words

    # اسم ملف آمن
    r = row.as_dict() if hasattr(row, "as_dict") else dict(row)
    display_name = (frappe.utils.cstr(r.get("customer_name") or r.get("customer") or "customer")).strip()
    safe_name = re.sub(r'[\\/:*?"<>|]+', "-", display_name) or "customer"
    fname = f"{safe_name}.pdf"

    # تحضير البيانات للتنسيق
    audit = frappe.get_doc("Audit Office for Certifications", doc.audit_office) if doc.get("audit_office") else None
    date_str = formatdate(doc.date) if doc.get("date") else formatdate(now_datetime())
    
    currency = r.get("currency") or doc.get("currency") or "SAR"
    balance = float(r.get("balance") or 0)
    formatted_balance = "{:,.2f}".format(balance)
    
    customer_vat_reg_no = frappe.db.get_value("Customer", r.get("customer"), 'custom_vat_registration_number')
    buyer_address = r.get('customer_address')
    
    if buyer_address:
        address_info = frappe.db.get_value('Address', buyer_address, 
                                         ["address_line1", "city", "state", "pincode"], as_dict=True)
        buyer_street = address_info.address_line1 if address_info else None
        buyer_city = address_info.city if address_info else None
        buyer_district = address_info.state if address_info else None
        buyer_postal_code = address_info.pincode if address_info else None
    else:
        buyer_street, buyer_city, buyer_district, buyer_postal_code = None, None, None, None

    # بناء HTML يدويًا باستخدام التنسيق المطلوب
    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
      <meta charset="utf-8" />
      <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
      <style type="text/css">
        /* Reset and Base Settings for wkhtmltopdf */
        * {{
          margin: 0;
          padding: 0;
          box-sizing: border-box;
          -webkit-print-color-adjust: exact;
          print-color-adjust: exact;
        }}

        /* Page Settings for wkhtmltopdf */
        @page {{
          size: A4;
          margin: 0;
        }}

        @media print {{
          html, body {{
            width: 210mm;
            height: 297mm;
            margin: 0;
            padding: 0;
          }}
        }}

        html {{
          font-size: 14px;
          -webkit-text-size-adjust: 100%;
          margin: 0;
          padding: 0;
          width: 100%;
        }}

        body {{
          margin: 0;
          padding: 10mm;
          width: 100%;
          min-height: 297mm;
          direction: rtl;
          text-align: right;
          font-family: "Arial", "Tahoma", sans-serif;
          font-size: 14px;
          line-height: 1.6;
          color: #000000;
          background-color: #ffffff;
          display: block;
        }}

        /* Container */
        .page {{
          width: 100%;
          margin: 0;
          padding: 0;
          background-color: #ffffff;
          page-break-after: always;
          display: block;
          position: relative;
        }}

        .page:last-child {{
          page-break-after: auto;
        }}

        /* Header Styles */
        .header {{
          text-align: center;
          padding: 12px;
          margin-bottom: 12px;
          border: 2px solid #000000;
          background-color: #ffffff;
          page-break-inside: avoid;
          width: 100%;
        }}

        .company-info {{
          margin-bottom: 10px;
          padding-bottom: 10px;
          border-bottom: 2px solid #000000;
          width: 100%;
        }}

        .company-name {{
          font-size: 22px;
          font-weight: bold;
          margin-bottom: 8px;
          color: #000000;
        }}

        .company-details-table {{
          width: 100%;
          margin: 8px auto;
          table-layout: fixed;
        }}

        .company-details-row {{
          text-align: center;
          font-size: 12px;
          color: #333333;
        }}

        .company-details-row td {{
          padding: 2px 8px;
          vertical-align: middle;
          text-align: center;
        }}

        .detail-label {{
          font-weight: bold;
          color: #000000;
        }}

        .detail-separator {{
          color: #999999;
          padding: 0 5px;
        }}

        .main-title {{
          font-size: 20px;
          font-weight: bold;
          margin: 10px 0 8px 0;
          color: #000000;
        }}

        .date-info {{
          display: inline-block;
          font-size: 14px;
          font-weight: bold;
          padding: 4px 15px;
          border: 1px solid #666666;
          background-color: #ffffff;
        }}

        /* Content Box */
        .content-box {{
          background-color: #ffffff;
          border: 1px solid #999999;
          padding: 12px;
          margin-bottom: 12px;
          page-break-inside: avoid;
          width: 100%;
        }}

        .customer-greeting {{
          font-size: 14px;
          margin-bottom: 10px;
          padding: 8px 10px;
          background-color: #f5f5f5;
          border-right: 3px solid #333333;
        }}

        .customer-name {{
          color: #000000;
          font-weight: bold;
          font-size: 15px;
        }}

        .greeting-text {{
          text-align: center;
          font-style: italic;
          margin: 10px 0;
          color: #333333;
          font-size: 13px;
        }}

        /* Balance Section */
        .balance-section {{
          border: 2px solid #000000;
          padding: 12px;
          margin: 15px 0;
          text-align: center;
          background-color: #fafafa;
          page-break-inside: avoid;
        }}

        .balance-label {{
          font-size: 13px;
          margin-bottom: 8px;
          color: #333333;
        }}

        .balance-amount {{
          font-size: 22px;
          font-weight: bold;
          margin: 8px 0;
          color: #000000;
          direction: ltr;
          unicode-bidi: embed;
        }}

        .balance-words {{
          font-style: italic;
          font-size: 12px;
          margin-top: 8px;
          color: #555555;
          direction: ltr;
          unicode-bidi: embed;
        }}

        /* Instruction Text */
        .instruction-text {{
          margin: 10px 0;
          line-height: 1.8;
          color: #000000;
          padding: 10px;
          background-color: #f8f8f8;
          border-right: 3px solid #666666;
          font-size: 12px;
        }}

        /* Audit Info */
        .audit-info {{
          background-color: #f5f5f5;
          border: 1px solid #999999;
          padding: 10px;
          margin: 10px 0;
          color: #000000;
          font-size: 11px;
          line-height: 1.8;
          page-break-inside: avoid;
        }}

        .audit-office {{
          font-weight: bold;
          color: #000000;
        }}

        .closing-text {{
          text-align: center;
          font-weight: bold;
          margin: 15px 0 10px 0;
          color: #000000;
          font-size: 14px;
        }}

        /* Utility Classes */
        .text-center {{ text-align: center; }}
        .text-right {{ text-align: right; }}
        .bold {{ font-weight: bold; }}
        .mb-10 {{ margin-bottom: 10px; }}

        /* wkhtmltopdf specific fixes */
        table {{
          border-collapse: collapse;
          border-spacing: 0;
        }}

        /* Prevent content overflow */
        .page * {{
          word-wrap: break-word;
          overflow-wrap: break-word;
        }}

        /* Clear floats */
        .clearfix:after {{
          content: "";
          display: table;
          clear: both;
        }}
      </style>
    </head>
    <body>
      <div class="page">
        <!-- Header Section -->
        <div class="header">
          <div class="company-info">
            <div class="company-name">شركة نكهة المشروب للتجارة</div>
            <table class="company-details-table" align="center" cellpadding="0" cellspacing="0">
              <tr class="company-details-row">
                <td style="text-align: center; width: 100%;">
                  <span class="detail-label">الرقم الضريبي:</span> 311003515800003
                  <span class="detail-separator">|</span>
                  <span class="detail-label">السجل التجاري:</span> 1010598153
                </td>
              </tr>
            </table>
          </div>
          <h1 class="main-title">مطابقة رصيد العميل</h1>
          <div class="date-info">{date_str}</div>
        </div>

        <!-- Content Section -->
        <div class="content-box">
          <div class="customer-greeting">
            السادة / <span class="customer-name">{r.get('customer_name') or r.get('customer')}</span>
    """

    # إضافة معلومات العنوان إذا كانت متاحة
    if buyer_street or buyer_city or buyer_district:
        html += f"""
            <div style="font-size: 11px; margin-top: 4px; color: #555555;">
              {buyer_street or ''}
              {', ' + buyer_city if buyer_city else ''}
              {', ' + buyer_district if buyer_district else ''}
              {' - ' + buyer_postal_code if buyer_postal_code else ''}
            </div>
        """

    # إضافة الرقم الضريبي للعميل إذا كان متاحاً
    if customer_vat_reg_no:
        html += f"""
            <div style="font-size: 11px; margin-top: 4px; color: #555555;">
              <span class="detail-label">الرقم الضريبي:</span> {customer_vat_reg_no}
            </div>
        """

    html += f"""
          </div>
          
          <div class="greeting-text">بعد التحية،</div>

          <div class="balance-section">
            <div class="balance-label">
              نود أن نفيدكم أن رصيدكم لدينا حتى تاريخ <strong>{date_str}</strong>
            </div>
            <div class="balance-amount">{formatted_balance} {currency}</div>
            <div class="balance-words">({money_in_words(balance, currency)})</div>
          </div>

          <div class="instruction-text">
            للتحقق من صحة هذا الرصيد نرجو مراجعته مع سجلاتكم وإرسال مصادقتكم مباشرة إلى مراجعي حساباتنا.
          </div>
    """

    # إضافة معلومات المراجعة إذا كانت متاحة
    if audit:
        html += f"""
          <div class="audit-info">
            <div class="mb-10">
              السادة / <span class="audit-office">{audit.office_name}</span>، وذلك باستكمال الجزء السفلي من هذا الخطاب.
            </div>
            <div>
              ترسل المصادقة إلى السادة / {audit.office_name}
              على عنوان بريد:
              {', ' + audit.postal_address if audit.postal_address else ''}
              {', أو عبر البريد الإلكتروني ' + audit.e_mail if audit.e_mail else ''}
              {', أو على الفاكس ' + audit.fax if audit.fax else ''}
              ، في أقرب وقت ممكن.
            </div>
          </div>
        """

    html += f"""
          <div class="closing-text">وتفضلوا بقبول فائق الاحترام،</div>
        </div>
      </div>
    </body>
    </html>
    """

    # خيارات wkhtmltopdf
    wkhtml_options = wkhtml_options or {
        "page-size": "A4",
        "encoding": "UTF-8",
        "margin-top": "12mm",
        "margin-right": "10mm",
        "margin-bottom": "14mm",
        "margin-left": "12mm",
        "print-media-type": "",
        "no-outline": "",
        "background": "",
        "enable-local-file-access": "",
        "quiet": "",
    }

    return fname, get_pdf(html, options=wkhtml_options)




def _visible_rows(doc):
    return [r for r in (doc.customer_balance or []) if getattr(r, "visible_in_batch", 0) == 1]


@frappe.whitelist()
def send_customer_pages_via_email(docname: str, from_email: str | None = None, email_template: str | None = None):
    doc = frappe.get_doc("Customer Authentications", docname)
    rows = _visible_rows(doc)
    if not rows:
        frappe.throw(_("No visible rows to send."))

    total = 0
    for row in rows:
        email = (row.email or "").strip() or _get_primary_email_for_customer(row.customer)
        if not email:
            continue

        ctx = {
            "customer": row.customer,
            "customer_name": row.customer_name or row.customer,
            "balance": row.balance or 0,
            "docname": doc.name,
        }

        if email_template:
            et = frappe.get_doc("Email Template", email_template)
            subj_t = et.subject or _("Notification")
            body_t = getattr(et, "response", None) or getattr(et, "response_html", None) or getattr(et, "response_", "") or ""
            subject = frappe.render_template(subj_t, ctx)
            message = frappe.render_template(body_t, ctx)
        else:
            subject = _("Your Statement")
            message = frappe.render_template(
                _("Hello {{ customer_name }},<br>Your balance is {{ balance }}."),
                {"customer_name": ctx["customer_name"], "balance": frappe.utils.fmt_money(ctx["balance"])},
            )

        fname, pdf_bytes = _render_customer_page_pdf(doc, row)

        try:
            frappe.sendmail(
                recipients=[email],
                subject=subject,
                message=message,
                sender=from_email or None,
                attachments=[{"fname": fname, "fcontent": pdf_bytes}],
                expose_recipients="to",
            )
            total += 1
        except Exception as e:
            frappe.log_error(f"Email send failed to {email}: {e}", "send_customer_pages_via_email")

    return {"sent_count": total}


@frappe.whitelist()
def export_customer_pages_zip(docname: str):
    doc = frappe.get_doc("Customer Authentications", docname)
    rows = _visible_rows(doc)
    if not rows:
        frappe.throw(_("No visible rows to export."))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in rows:
            fname, pdf_bytes = _render_customer_page_pdf(doc, r)
            zf.writestr(fname, pdf_bytes)

    content = buf.getvalue()
    buf.close()

    zip_name = f"{doc.name}.zip"
    f = save_file(zip_name, content, "Customer Authentications", doc.name, is_private=1)
    return {"file_url": f.file_url, "file_name": f.file_name}


def _rows_as_dicts(doc):
    cols = [
        "customer",
        "customer_name",
        "email",
        "balance",
        "status_send",
        "attempts",
        "send_at",         # لو عندك الحقل اسمه sent_at بدّله هنا
        "delivery_message",
        "visible_in_batch",
    ]
    out = []
    for r in doc.customer_balance or []:
        if getattr(r, "visible_in_batch", 0) != 1:
            continue
        d = {}
        for c in cols:
            v = getattr(r, c, None)
            if c == "send_at" and v:
                try:
                    v = frappe.utils.format_datetime(v)
                except Exception:
                    pass
            d[c] = v
        out.append(d)
    return out


@frappe.whitelist()
def export_customer_rows_excel(docname: str):
    doc = frappe.get_doc("Customer Authentications", docname)
    rows = _rows_as_dicts(doc)
    if not rows:
        frappe.throw(_("No visible rows to export."))

    headers = list(rows[0].keys())
    data = [headers] + [[r.get(h, "") for h in headers] for r in rows]

    try:
        from frappe.utils.xlsxutils import make_xlsx
    except Exception:
        frappe.throw(_("XLSX export not available on this version."))

    xlsx_file = make_xlsx(data, "Customers")
    content = xlsx_file.getvalue()
    fname = f"{frappe.scrub(doc.name)}.xlsx"
    f = save_file(fname, content, "Customer Authentications", doc.name, is_private=1)
    return {"file_url": f.file_url, "file_name": f.file_name}


@frappe.whitelist()
def export_customer_rows_csv(docname: str):
    doc = frappe.get_doc("Customer Authentications", docname)
    rows = _rows_as_dicts(doc)
    if not rows:
        frappe.throw(_("No visible rows to export."))

    headers = list(rows[0].keys())
    sio = io.StringIO()
    writer = csv.writer(sio)
    writer.writerow(headers)
    for r in rows:
        writer.writerow([r.get(h, "") for h in headers])

    content = sio.getvalue().encode("utf-8-sig")
    sio.close()

    fname = f"{frappe.scrub(doc.name)}.csv"
    f = save_file(fname, content, "Customer Authentications", doc.name, is_private=1)
    return {"file_url": f.file_url, "file_name": f.file_name}
